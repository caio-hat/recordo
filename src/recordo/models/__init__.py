"""Models download backend (M2).

Funções para download/install/remove de modelos:
  - Whisper: huggingface_hub.snapshot_download para Systran/faster-whisper-*
  - Parakeet: NeMo from_pretrained (lazy cache em ~/.cache/nemo)
  - Ollama: subprocess 'ollama pull/rm' com parsing de progresso

Todos os downloads são MANUAIS — chamados via UI Models Manager. Setup.sh
nunca baixa modelos. Threading.Event para cancellation.
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
import threading
from collections.abc import Callable
from pathlib import Path

log = logging.getLogger(__name__)


# Status callback signature: (percentage_0_to_100: float, status_msg: str) -> None
ProgressCallback = Callable[[float, str], None]


# Cache dirs
HF_CACHE = Path.home() / ".cache" / "huggingface" / "hub"
NEMO_CACHE = Path.home() / ".cache" / "huggingface" / "hub"  # NeMo usa HF cache


# ── Whisper ─────────────────────────────────────────────────────────────────


def is_whisper_installed(model_id: str) -> bool:
    """Detecta se modelo Whisper já foi baixado via cache HF."""
    # HF cache layout: models--Systran--faster-whisper-large-v3-turbo/snapshots/<hash>/
    hf_dir_name = "models--" + model_id.replace("/", "--")
    target = HF_CACHE / hf_dir_name
    if not target.exists():
        return False
    # Precisa ter pelo menos um snapshot com model.bin
    snapshots = target / "snapshots"
    if not snapshots.exists():
        return False
    for snap in snapshots.iterdir():
        if (snap / "model.bin").exists() or any(snap.glob("*.bin")):
            return True
    return False


def download_whisper(
    model_id: str,
    *,
    on_progress: ProgressCallback | None = None,
    cancel_event: threading.Event | None = None,
) -> bool:
    """Baixa modelo Whisper via huggingface_hub.snapshot_download.

    Args:
        model_id: ex 'Systran/faster-whisper-large-v3-turbo'
        on_progress: callback (pct, msg). HF não dá pct exato; emitimos
                     progressões discretas (0% start, 50% mid, 100% done).
        cancel_event: threading.Event para cancelar (best-effort)

    Returns True se sucesso.
    """
    if on_progress:
        on_progress(0.0, "Iniciando download…")

    if cancel_event and cancel_event.is_set():
        return False

    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        if on_progress:
            on_progress(0.0, "huggingface_hub não instalado")
        log.error("huggingface_hub indisponível — instale via pip")
        return False

    if on_progress:
        on_progress(10.0, f"Baixando {model_id}…")

    try:
        snapshot_download(repo_id=model_id, cache_dir=str(HF_CACHE))
    except Exception as e:
        log.exception("download whisper falhou: %s", e)
        if on_progress:
            on_progress(0.0, f"Erro: {str(e)[:100]}")
        return False

    if cancel_event and cancel_event.is_set():
        return False

    if on_progress:
        on_progress(100.0, "✓ Instalado")
    return True


def remove_whisper(model_id: str) -> bool:
    """Remove modelo Whisper do cache HF."""
    hf_dir_name = "models--" + model_id.replace("/", "--")
    target = HF_CACHE / hf_dir_name
    if not target.exists():
        return False
    try:
        shutil.rmtree(target)
        log.info("removido: %s", target)
        return True
    except OSError as e:
        log.warning("falha remover %s: %s", target, e)
        return False


def get_whisper_size_on_disk(model_id: str) -> int:
    """Retorna bytes ocupados em disco pelo modelo (0 se ausente)."""
    hf_dir_name = "models--" + model_id.replace("/", "--")
    target = HF_CACHE / hf_dir_name
    if not target.exists():
        return 0
    total = 0
    for f in target.rglob("*"):
        if f.is_file():
            try:
                total += f.stat().st_size
            except OSError:
                pass
    return total


# ── Parakeet ONNX (sherpa-onnx) ───────────────────────────────────────────────


def is_parakeet_onnx_installed(
    model_id: str = "istupakov/parakeet-tdt-0.6b-v3-onnx",
) -> bool:
    """Detecta Parakeet ONNX via cache HF."""
    from ..transcribers.parakeet_onnx import is_installed

    return is_installed(model_id)


def download_parakeet_onnx(
    model_id: str = "istupakov/parakeet-tdt-0.6b-v3-onnx",
    *,
    on_progress: ProgressCallback | None = None,
    cancel_event: threading.Event | None = None,
) -> bool:
    """Baixa modelo Parakeet ONNX via HF snapshot."""
    if on_progress:
        on_progress(0.0, "Iniciando download Parakeet ONNX…")
    if cancel_event and cancel_event.is_set():
        return False
    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        if on_progress:
            on_progress(0.0, "huggingface_hub não instalado")
        log.error("huggingface_hub indisponível")
        return False
    if on_progress:
        on_progress(10.0, f"Baixando {model_id}…")
    try:
        snapshot_download(
            repo_id=model_id,
            cache_dir=str(HF_CACHE),
            allow_patterns=["*.onnx", "*.txt", "*.yaml", "*.json"],
        )
    except Exception as e:
        log.exception("download parakeet onnx falhou: %s", e)
        if on_progress:
            on_progress(0.0, f"Erro: {str(e)[:100]}")
        return False
    if cancel_event and cancel_event.is_set():
        return False
    if on_progress:
        on_progress(100.0, "✓ Instalado")
    return True


# ── Parakeet (NeMo) ──────────────────────────────────────────────────────────


def is_parakeet_installed(model_id: str) -> bool:
    """Detecta Parakeet via cache HF (NeMo usa HF hub).

    Modelos NeMo são .nemo files dentro do snapshot do HF.
    """
    hf_dir_name = "models--" + model_id.replace("/", "--")
    target = HF_CACHE / hf_dir_name
    if not target.exists():
        return False
    # Procura .nemo em snapshots
    for nemo_file in target.rglob("*.nemo"):
        if nemo_file.is_file():
            return True
    return False


def download_parakeet(
    model_id: str,
    *,
    on_progress: ProgressCallback | None = None,
    cancel_event: threading.Event | None = None,
) -> bool:
    """Baixa Parakeet via NeMo from_pretrained (que usa HF hub).

    Requer nemo_toolkit instalado. Se faltar, retorna False com msg
    pra UI orientar `pip install nemo_toolkit[asr]`.
    """
    if on_progress:
        on_progress(0.0, "Verificando NeMo…")

    try:
        import nemo.collections.asr as nemo_asr  # type: ignore[import-not-found]
    except ImportError:
        if on_progress:
            on_progress(0.0, "NeMo não instalado")
        log.warning("nemo_toolkit ausente; user precisa instalar manualmente")
        return False

    if cancel_event and cancel_event.is_set():
        return False

    if on_progress:
        on_progress(10.0, f"Baixando {model_id}…")

    try:
        # NeMo from_pretrained baixa via HF cache automaticamente
        nemo_asr.models.EncDecRNNTBPEModel.from_pretrained(model_id)
    except Exception as e:
        # Tenta via huggingface_hub direto como fallback
        try:
            from huggingface_hub import snapshot_download

            snapshot_download(repo_id=model_id, cache_dir=str(HF_CACHE))
        except Exception as e2:
            log.exception("download parakeet falhou: %s / %s", e, e2)
            if on_progress:
                on_progress(0.0, f"Erro: {str(e)[:100]}")
            return False

    if on_progress:
        on_progress(100.0, "✓ Instalado")
    return True


def remove_parakeet(model_id: str) -> bool:
    """Remove modelo Parakeet do cache HF."""
    return remove_whisper(model_id)  # mesmo cache layout


# ── Ollama ───────────────────────────────────────────────────────────────────


def is_ollama_installed(model_id: str) -> bool:
    """Detecta se modelo está em `ollama list`."""
    try:
        r = subprocess.run(
            ["ollama", "list"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if r.returncode != 0:
            return False
        # Output: NAME ID SIZE MODIFIED
        # gemma2:2b  abc123 1.6GB 2 days ago
        for line in r.stdout.splitlines()[1:]:  # skip header
            parts = line.split()
            if parts and parts[0] == model_id:
                return True
        return False
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def download_ollama(
    model_id: str,
    *,
    on_progress: ProgressCallback | None = None,
    cancel_event: threading.Event | None = None,
) -> bool:
    """Baixa modelo Ollama via 'ollama pull <name>' com parse de progresso.

    Output do ollama pull tem linhas como:
      pulling manifest
      pulling 8db5a7faaab1: 12% ▕███       ▏ 200 MB/1.6 GB ...
      success
    """
    if not shutil.which("ollama"):
        if on_progress:
            on_progress(0.0, "Ollama CLI não instalado")
        return False

    if on_progress:
        on_progress(0.0, f"Baixando {model_id} via ollama pull…")

    try:
        proc = subprocess.Popen(
            ["ollama", "pull", model_id],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
    except OSError as e:
        log.exception("falha spawn ollama pull: %s", e)
        if on_progress:
            on_progress(0.0, f"Erro: {e}")
        return False

    pct_re = re.compile(r"(\d{1,3})%")
    last_pct = 0.0

    try:
        if proc.stdout is None:
            proc.wait()
            return proc.returncode == 0
        for line in proc.stdout:
            if cancel_event and cancel_event.is_set():
                proc.terminate()
                return False
            line = line.strip()
            if not line:
                continue
            m = pct_re.search(line)
            if m:
                pct = float(m.group(1))
                if pct > last_pct:
                    last_pct = pct
                    if on_progress:
                        on_progress(pct, line[:80])
            elif "success" in line.lower():
                last_pct = 100.0
                if on_progress:
                    on_progress(100.0, "✓ Instalado")
        proc.wait()
    except Exception as e:
        log.exception("erro durante ollama pull: %s", e)

    success = proc.returncode == 0
    if success and last_pct < 100:
        if on_progress:
            on_progress(100.0, "✓ Instalado")
    return success


def remove_ollama(model_id: str) -> bool:
    """Remove modelo Ollama via 'ollama rm <name>'."""
    if not shutil.which("ollama"):
        return False
    try:
        r = subprocess.run(
            ["ollama", "rm", model_id],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return r.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def get_ollama_size_on_disk(model_id: str) -> int:
    """Lê tamanho via 'ollama list' parsing."""
    try:
        r = subprocess.run(
            ["ollama", "list"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if r.returncode != 0:
            return 0
        for line in r.stdout.splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 3 and parts[0] == model_id:
                # SIZE column: e.g. "1.6GB" or "200MB"
                size_str = parts[2]
                m = re.match(r"([\d.]+)\s*(GB|MB|KB)", size_str, re.IGNORECASE)
                if m:
                    val = float(m.group(1))
                    unit = m.group(2).upper()
                    multiplier = {"KB": 1024, "MB": 1024**2, "GB": 1024**3}[unit]
                    return int(val * multiplier)
        return 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return 0
