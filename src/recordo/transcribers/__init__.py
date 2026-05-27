"""Backends de transcrição plugáveis (Whisper, Parakeet, Cohere).

Comparação rápida (Open ASR Leaderboard 2026):
  - Cohere Transcribe (5.42% WER)  : SOTA, 3x mais rápido, API ou self-host
  - Parakeet TDT v3   (6.34% WER)  : 25 idiomas EU, native em CPU
  - Whisper Large-v3  (7.44% WER)  : 99 idiomas, mais maduro, totalmente local
  - Whisper Large-v3-Turbo (7.75%) : 3x mais rápido que Large-v3
"""

from __future__ import annotations

from typing import Any

from .base import Transcriber, TranscriptionResult, TranscriptionSegment

__all__ = ["Transcriber", "TranscriptionResult", "TranscriptionSegment", "get_transcriber"]


def get_transcriber(backend: str, config: dict[str, Any]) -> Transcriber:
    """Factory: retorna Transcriber pra backend nomeado.

    Backends suportados:
      - 'whisper'  : faster-whisper local (lazy install via setup --with-transcribe)
      - 'parakeet' : NVIDIA NeMo Parakeet TDT v3 (lazy install via setup --with-parakeet)
      - 'cohere'   : Cohere Transcribe via API HTTP (precisa COHERE_API_KEY)

    Imports são lazy pra evitar carregar PyTorch/NeMo no startup.
    """
    backend = backend.lower()
    if backend == "whisper":
        from .whisper import WhisperTranscriber

        return WhisperTranscriber(config.get("whisper", {}))
    if backend == "parakeet":
        from .parakeet import ParakeetTranscriber

        return ParakeetTranscriber(config.get("parakeet", {}))
    if backend == "cohere":
        from .cohere import CohereTranscriber

        return CohereTranscriber(config.get("cohere", {}))
    raise ValueError(f"backend desconhecido: {backend!r} (use 'whisper', 'parakeet' ou 'cohere')")


def available_backends() -> list[str]:
    """Lista backends técnicamente disponíveis no ambiente."""
    out = ["cohere"]  # cohere é HTTP-only, sempre técnicamente disponível
    try:
        import faster_whisper  # noqa: F401

        out.insert(0, "whisper")
    except ImportError:
        pass
    try:
        import nemo.collections.asr  # type: ignore[import-not-found]  # noqa: F401

        out.append("parakeet")
    except ImportError:
        pass
    return out
