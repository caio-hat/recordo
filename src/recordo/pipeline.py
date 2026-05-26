"""Pós-pipeline: mover áudio pra ~/Notas, gerar nota.md, transcrever (lazy)."""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import NOTAS_DIR, load_config
from .notify import notify
from .recorder import Mark, SessionState
from .subject import safe_subject
from .transcribers import TranscriptionResult, get_transcriber

log = logging.getLogger(__name__)

WHISPER_PKGS = ["faster-whisper>=1.0"]
PLACEHOLDER = "_(processando — esta seção é preenchida quando o backend terminar)_"


def _safe_move(src: Path, dst: Path) -> None:
    """Move detectando cross-filesystem.

    Em mesmo FS: rename atômico (instantâneo).
    Cross-FS: shutil.move faz copy+unlink — pode demorar; logamos warning
    explícito pra debug se um move grande aparecer durante stop.
    """
    try:
        src_dev = src.stat().st_dev
        dst_dev = dst.parent.stat().st_dev
        if src_dev != dst_dev:
            size_mb = src.stat().st_size / (1024 * 1024)
            log.warning(
                "cross-filesystem move: %s → %s (%.1fMB, copy+unlink)",
                src,
                dst,
                size_mb,
            )
    except FileNotFoundError:
        pass
    shutil.move(str(src), str(dst))


def transcribe(audio_path: Path, *, model_size: str = "large-v3-turbo", language: str = "pt") -> Path:
    """[legacy] Transcreve com Whisper. Mantida pra compat.

    Novo código deve usar `get_transcriber(...).transcribe(audio)` →
    `TranscriptionResult.write_txt/write_srt`.
    """
    transcriber = get_transcriber("whisper", {"whisper": {"model": model_size}})
    result = transcriber.transcribe(audio_path, language=language)
    txt_out = audio_path.parent / "transcricao.txt"
    srt_out = audio_path.parent / "transcricao.srt"
    result.write_txt(txt_out)
    result.write_srt(srt_out)
    return txt_out


def ensure_whisper_installed() -> bool:
    """Verifica + instala faster-whisper no venv corrente, se faltar."""
    try:
        import faster_whisper  # noqa: F401

        return True
    except ImportError:
        pass
    log.info("instalando faster-whisper (lazy) — pode demorar na 1ª vez")
    uv = shutil.which("uv")
    cmd = (
        [uv, "pip", "install", "--python", sys.executable, *WHISPER_PKGS]
        if uv
        else [sys.executable, "-m", "pip", "install", *WHISPER_PKGS]
    )
    try:
        subprocess.check_call(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        import importlib

        importlib.invalidate_caches()
        return True
    except subprocess.CalledProcessError as e:
        log.error("falha ao instalar faster-whisper: %s", e)
        return False


def _format_mark(m: Mark) -> str:
    h, m_, s = int(m.ts_seconds // 3600), int((m.ts_seconds % 3600) // 60), int(m.ts_seconds % 60)
    return f"- [{h:02d}:{m_:02d}:{s:02d}] {m.text or '(marca)'}"


def _render_nota_md(
    state: SessionState, marks: list[Mark], target_dir: Path, backend_name: str = "pending"
) -> None:
    """Gera nota.md inicial com placeholder. Backend nome ajustado depois."""
    duration_min = sum(s.duration for s in state.segments) / 60
    marks_block = "\n".join(_format_mark(m) for m in marks) or "_(nenhuma marca registrada)_"
    nota_md = target_dir / "nota.md"
    nota_md.write_text(
        f"""---
subject: {state.subject}
date: {state.started_at}
duration_min: {duration_min:.1f}
audio: ./audio.opus
transcricao: ./transcricao.txt
segments: {len(state.segments)}
auto_started: {state.auto_started}
backend: {backend_name}
tags: [reuniao]
---

# {state.subject}

## Marcas durante gravação

{marks_block}

## Notas manuais


## Transcrição

{PLACEHOLDER}
""",
        encoding="utf-8",
    )


def post_pipeline(
    state: SessionState,
    final_audio: Path,
    marks: list[Mark],
    *,
    config: dict[str, Any] | None = None,
    whisper_model: str | None = None,  # backward-compat
    language: str | None = None,
) -> Path | None:
    """Move áudio pra ~/Notas/, gera nota.md, spawn transcrição em thread.

    Backend de transcrição escolhido por `config['transcriber']['backend']`
    (default config.toml: whisper). Argumentos kwargs legacy ainda funcionam.
    """
    if not final_audio or not final_audio.exists():
        return None

    cfg = config if config is not None else load_config()
    transcriber_cfg = cfg.get("transcriber", {})
    backend = transcriber_cfg.get("backend", "whisper")
    lang = language or transcriber_cfg.get("language", "pt")

    # backward-compat: parâmetro antigo whisper_model sobrescreve
    if whisper_model:
        transcriber_cfg.setdefault("whisper", {})["model"] = whisper_model

    date_str = datetime.fromisoformat(state.started_at).strftime("%Y-%m-%d")
    safe = safe_subject(state.subject)
    target_dir = NOTAS_DIR / f"{date_str}_{safe}"
    target_dir.mkdir(parents=True, exist_ok=True)

    audio_dst = target_dir / "audio.opus"
    _safe_move(final_audio, audio_dst)

    src_dir = Path(state.output_dir)
    for extra in src_dir.glob("*_report.md"):
        _safe_move(extra, target_dir / extra.name)

    nota_md = target_dir / "nota.md"
    _render_nota_md(state, marks, target_dir, backend_name=backend)

    threading.Thread(
        target=_transcribe_async,
        args=(audio_dst, nota_md, backend, transcriber_cfg, lang, target_dir),
        daemon=False,
        name="recordo-transcribe",
    ).start()
    return target_dir


def _transcribe_async(
    audio_dst: Path,
    nota_md: Path,
    backend: str,
    transcriber_cfg: dict[str, Any],
    language: str,
    target_dir: Path,
) -> None:
    try:
        if backend == "whisper" and not ensure_whisper_installed():
            notify(
                "⚠️ Transcrição indisponível",
                "faster-whisper não instalado. Áudio em ~/Notas/.",
                urgency="critical",
            )
            return

        transcriber = get_transcriber(backend, transcriber_cfg)
        result = transcriber.transcribe(audio_dst, language=language)
        _write_result(audio_dst, nota_md, result)
        notify("✓ Nota disponível", f"~/Notas/{target_dir.name}/", icon="document-edit", transient=True)
    except Exception as e:
        log.exception("falha transcrição async: %s", e)
        notify("⚠️ Erro transcrição", str(e)[:120], urgency="critical")


def _write_result(audio_dst: Path, nota_md: Path, result: TranscriptionResult) -> None:
    """Persiste arquivos de transcrição e atualiza nota.md."""
    txt_out = audio_dst.parent / "transcricao.txt"
    srt_out = audio_dst.parent / "transcricao.srt"
    result.write_txt(txt_out)
    result.write_srt(srt_out)

    nota = nota_md.read_text(encoding="utf-8")
    embedded = txt_out.read_text(encoding="utf-8")
    nota = nota.replace(PLACEHOLDER, f"```\n{embedded}\n```")
    # atualiza linha backend no frontmatter se já existir
    if "backend:" in nota:
        import re

        nota = re.sub(r"^backend:.*$", f"backend: {result.backend}", nota, count=1, flags=re.M)
    nota_md.write_text(nota, encoding="utf-8")


def retranscribe(
    target_dir: Path,
    *,
    backend: str = "whisper",
    transcriber_cfg: dict[str, Any] | None = None,
    language: str = "pt",
) -> TranscriptionResult:
    """Re-transcreve uma gravação existente em ~/Notas/ com outro backend.

    Usado pela GUI Page Transcribe. Sobrescreve transcricao.{txt,srt} e nota.md.
    """
    audio = target_dir / "audio.opus"
    if not audio.exists():
        raise FileNotFoundError(f"audio.opus ausente em {target_dir}")
    nota_md = target_dir / "nota.md"
    if not nota_md.exists():
        raise FileNotFoundError(f"nota.md ausente em {target_dir}")

    transcriber = get_transcriber(backend, transcriber_cfg or {})
    result = transcriber.transcribe(audio, language=language)

    # Restaura placeholder pra _write_result substituir corretamente
    nota = nota_md.read_text(encoding="utf-8")
    if PLACEHOLDER not in nota:
        # já tinha transcrição antiga — remove bloco ``` ``` final pra substituir
        import re

        nota = re.sub(
            r"## Transcrição\s*\n+```.*?```\s*$",
            f"## Transcrição\n\n{PLACEHOLDER}\n",
            nota,
            flags=re.DOTALL,
        )
        nota_md.write_text(nota, encoding="utf-8")

    _write_result(audio, nota_md, result)
    log.info("re-transcrição completa: %s (%s)", target_dir.name, result.backend)
    return result
