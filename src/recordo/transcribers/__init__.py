"""Backends de transcrição plugáveis (Whisper, Parakeet)."""

from __future__ import annotations

from typing import Any

from .base import Transcriber, TranscriptionResult, TranscriptionSegment

__all__ = ["Transcriber", "TranscriptionResult", "TranscriptionSegment", "get_transcriber"]


def get_transcriber(backend: str, config: dict[str, Any]) -> Transcriber:
    """Factory: retorna Transcriber pra backend nomeado.

    Imports são lazy pra evitar carregar PyTorch/NeMo no startup.
    """
    backend = backend.lower()
    if backend == "whisper":
        from .whisper import WhisperTranscriber

        return WhisperTranscriber(config.get("whisper", {}))
    if backend == "parakeet":
        from .parakeet import ParakeetTranscriber

        return ParakeetTranscriber(config.get("parakeet", {}))
    raise ValueError(f"backend desconhecido: {backend!r} (use 'whisper' ou 'parakeet')")


def available_backends() -> list[str]:
    """Lista backends disponíveis no venv atual (checa imports)."""
    out = []
    try:
        import faster_whisper  # noqa: F401

        out.append("whisper")
    except ImportError:
        pass
    try:
        import nemo.collections.asr  # type: ignore[import-not-found]  # noqa: F401

        out.append("parakeet")
    except ImportError:
        pass
    return out
