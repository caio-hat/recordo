"""Pós-pipeline: mover áudio pra ~/Notas, gerar nota.md, transcrever (lazy)."""
from __future__ import annotations

import logging
import shutil
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

from .config import NOTAS_DIR
from .notify import notify
from .recorder import Mark, SessionState
from .subject import safe_subject

log = logging.getLogger(__name__)

WHISPER_PKGS = ["faster-whisper>=1.0"]


def _fmt_srt(t: float) -> str:
    h = int(t // 3600); m = int((t % 3600) // 60); s = t - h * 3600 - m * 60
    return f"{h:02d}:{m:02d}:{s:06.3f}".replace(".", ",")


def transcribe(audio_path: Path, *, model_size: str = "base",
               language: str = "pt") -> Path:
    """Transcreve áudio com faster-whisper. Gera .txt + .srt no mesmo dir."""
    from faster_whisper import WhisperModel  # type: ignore[import-not-found]

    log.info("carregando modelo Whisper '%s' (CPU int8)", model_size)
    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    log.info("transcrevendo %s", audio_path.name)

    segments, info = model.transcribe(
        str(audio_path), language=language, beam_size=5,
        vad_filter=True, vad_parameters={"min_silence_duration_ms": 500},
    )

    txt_out = audio_path.with_suffix(".txt")
    srt_out = audio_path.with_suffix(".srt")
    with txt_out.open("w") as ft, srt_out.open("w") as fs:
        for i, s in enumerate(segments, 1):
            ft.write(f"[{s.start:7.1f} → {s.end:7.1f}] {s.text.strip()}\n")
            fs.write(f"{i}\n{_fmt_srt(s.start)} --> {_fmt_srt(s.end)}\n{s.text.strip()}\n\n")
    log.info("transcrição: idioma=%s prob=%.2f", info.language, info.language_probability)
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
    cmd = ([uv, "pip", "install", "--python", sys.executable, *WHISPER_PKGS] if uv
           else [sys.executable, "-m", "pip", "install", *WHISPER_PKGS])
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


def post_pipeline(state: SessionState, final_audio: Path, marks: list[Mark],
                  *, whisper_model: str = "base", language: str = "pt") -> Optional[Path]:
    """Move áudio pra ~/Notas/, gera nota.md, spawn transcrição em thread."""
    if not final_audio or not final_audio.exists():
        return None

    date_str = datetime.fromisoformat(state.started_at).strftime("%Y-%m-%d")
    safe = safe_subject(state.subject)
    target_dir = NOTAS_DIR / f"{date_str}_{safe}"
    target_dir.mkdir(parents=True, exist_ok=True)

    audio_dst = target_dir / "audio.opus"
    shutil.move(str(final_audio), audio_dst)

    src_dir = Path(state.output_dir)
    for extra in src_dir.glob("*_report.md"):
        shutil.move(str(extra), target_dir / extra.name)

    duration_min = sum(s.duration for s in state.segments) / 60
    nota_md = target_dir / "nota.md"
    marks_block = "\n".join(_format_mark(m) for m in marks) or "_(nenhuma marca registrada)_"

    nota_md.write_text(f"""---
subject: {state.subject}
date: {state.started_at}
duration_min: {duration_min:.1f}
audio: ./audio.opus
transcricao: ./transcricao.txt
segments: {len(state.segments)}
auto_started: {state.auto_started}
tags: [reuniao]
---

# {state.subject}

## Marcas durante gravação

{marks_block}

## Notas manuais


## Transcrição

_(processando — esta seção é preenchida quando o faster-whisper terminar)_
""", encoding="utf-8")

    threading.Thread(target=_transcribe_async,
                     args=(audio_dst, nota_md, whisper_model, language, target_dir),
                     daemon=False, name="recordo-transcribe").start()
    return target_dir


def _transcribe_async(audio_dst: Path, nota_md: Path, model_size: str,
                      language: str, target_dir: Path) -> None:
    try:
        if not ensure_whisper_installed():
            notify("⚠️ Transcrição indisponível",
                   "faster-whisper não instalado. Áudio em ~/Notas/.",
                   urgency="critical")
            return
        txt = transcribe(audio_dst, model_size=model_size, language=language)
        transcricao_text = txt.read_text(encoding="utf-8")
        nota = nota_md.read_text(encoding="utf-8")
        nota = nota.replace(
            "_(processando — esta seção é preenchida quando o faster-whisper terminar)_",
            f"```\n{transcricao_text}\n```",
        )
        nota_md.write_text(nota, encoding="utf-8")
        notify("✓ Nota disponível", f"~/Notas/{target_dir.name}/",
               icon="document-edit", transient=True)
    except Exception as e:  # noqa: BLE001
        log.exception("falha transcrição async: %s", e)
        notify("⚠️ Erro transcrição", str(e)[:120], urgency="critical")
