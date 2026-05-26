"""WhisperTranscriber — faster-whisper backend (default)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from .base import Transcriber, TranscriptionResult, TranscriptionSegment

log = logging.getLogger(__name__)


class WhisperTranscriber(Transcriber):
    def __init__(self, config: dict[str, Any] | None = None):
        cfg = config or {}
        self.model_name: str = cfg.get("model", "large-v3-turbo")
        self.device: str = cfg.get("device", "cpu")
        self.compute_type: str = cfg.get("compute_type", "int8")
        self.beam_size: int = cfg.get("beam_size", 5)
        self.vad_filter: bool = cfg.get("vad_filter", True)
        self._model = None  # carrega no transcribe (lazy)

    @property
    def name(self) -> str:
        return f"whisper-{self.model_name}"

    def _load_model(self):
        if self._model is not None:
            return self._model
        from faster_whisper import WhisperModel  # type: ignore[import-not-found]

        log.info(
            "carregando Whisper '%s' device=%s compute=%s",
            self.model_name, self.device, self.compute_type,
        )
        self._model = WhisperModel(
            self.model_name, device=self.device, compute_type=self.compute_type,
        )
        return self._model

    def transcribe(self, audio: Path, *, language: str = "pt") -> TranscriptionResult:
        model = self._load_model()
        log.info("transcrevendo %s", audio.name)

        seg_iter, info = model.transcribe(
            str(audio),
            language=language,
            beam_size=self.beam_size,
            vad_filter=self.vad_filter,
            vad_parameters={"min_silence_duration_ms": 500} if self.vad_filter else None,
        )

        segments = [
            TranscriptionSegment(start=s.start, end=s.end, text=s.text)
            for s in seg_iter
        ]
        log.info(
            "whisper: %d segmentos, idioma=%s prob=%.2f",
            len(segments), info.language, info.language_probability,
        )
        return TranscriptionResult(
            segments=segments,
            language=info.language,
            language_probability=info.language_probability,
            backend=self.name,
        )
