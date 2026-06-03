"""Backends de transcrição plugáveis (Whisper, Parakeet, Cohere).

Comparação rápida (Open ASR Leaderboard 2026):
  - Cohere Transcribe (5.42% WER)  : SOTA, 3x mais rápido, API ou self-host
  - Parakeet TDT v3   (6.34% WER)  : 25 idiomas EU, native em CPU
  - Whisper Large-v3  (7.44% WER)  : 99 idiomas, mais maduro, totalmente local
  - Whisper Large-v3-Turbo (7.75%) : 3x mais rápido que Large-v3
"""

from __future__ import annotations

import threading as _threading
import time as _time
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
        engine = (config.get("parakeet") or {}).get("engine", "onnx")
        if engine == "nemo":
            from .parakeet import ParakeetTranscriber

            return ParakeetTranscriber(config.get("parakeet", {}))
        from .parakeet_onnx import ParakeetONNXTranscriber

        return ParakeetONNXTranscriber(config.get("parakeet", {}))
    if backend == "cohere":
        from .cohere import CohereTranscriber

        return CohereTranscriber(config.get("cohere", {}))
    if backend == "cohere_local":
        from .cohere_local import CohereLocalTranscriber

        return CohereLocalTranscriber(config.get("cohere_local", {}))
    raise ValueError(
        f"backend desconhecido: {backend!r} (use 'whisper', 'parakeet', 'cohere' ou 'cohere_local')"
    )


def _cached_for(seconds: float):
    """B9: TTL cache decorator (same as summarizer/__init__.py)."""

    def decorator(fn):
        lock = _threading.Lock()
        state: dict = {"value": None, "expires_at": 0.0}

        def wrapper(*args, **kwargs):
            now = _time.monotonic()
            with lock:
                if state["value"] is not None and now < state["expires_at"]:
                    return state["value"]
            value = fn(*args, **kwargs)
            with lock:
                state["value"] = value
                state["expires_at"] = now + seconds
            return value

        wrapper._cache_state = state  # type: ignore[attr-defined]
        wrapper._cache_clear = lambda: state.update(value=None, expires_at=0.0)  # type: ignore[attr-defined]
        return wrapper

    return decorator


@_cached_for(seconds=30.0)
def available_backends() -> list[str]:
    """Lista backends técnicamente disponíveis no ambiente. Cache TTL 30s (B9).

    Ordering (B11): whisper → parakeet → cohere (preferência local-first).
    """
    out: list[str] = []
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
    out.append("cohere")  # HTTP-only, sempre tecnicamente disponível
    return out
