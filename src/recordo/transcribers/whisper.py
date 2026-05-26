"""WhisperTranscriber — faster-whisper backend (default).

Anti-alucinação:
  Whisper tende a entrar em loop de frases curtas ("É isso. É isso. É isso.")
  em áudios com muito silêncio ou ruído. Os parâmetros abaixo são as defesas
  recomendadas (PR threads no faster-whisper #856, #1110):

  - condition_on_previous_text=False:
      Quebra a cadeia que alimenta o loop. Cada chunk é independente.
  - temperature=[0.0, 0.2, 0.4, 0.6, 0.8, 1.0]:
      Fallback dinâmico. Se a primeira tentativa (greedy, T=0) gerar texto
      com `compression_ratio` ou `log_prob` ruins, tenta de novo com
      temperatura crescente.
  - compression_ratio_threshold=2.4:
      Texto muito repetitivo tem ratio > 2.4 (gzip não comprime). Rejeita
      e dispara fallback.
  - log_prob_threshold=-1.0:
      Confiança baixa → fallback.
  - no_speech_threshold=0.6:
      Se modelo está 60%+ certo de que não há fala, descarta o chunk.

Locale UTF-8:
  PyAV (usado internamente pelo faster-whisper) tem bug onde os.strerror()
  retorna mensagens localizadas (pt_BR) e Python tenta decodar como ASCII.
  Forçamos LC_ALL=C.UTF-8 no env do processo antes de importar.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from .base import Transcriber, TranscriptionResult, TranscriptionSegment

log = logging.getLogger(__name__)

# Defesa anti-hallucination: temperatures pra fallback dinâmico
_TEMPERATURE_FALLBACK: tuple[float, ...] = (0.0, 0.2, 0.4, 0.6, 0.8, 1.0)


def _ensure_utf8_locale() -> None:
    """Força LC_ALL=C.UTF-8 antes de importar PyAV/faster-whisper.

    Mitiga UnicodeDecodeError 'ascii' codec em av/error.py:err_check
    quando os.strerror() retorna mensagens localizadas.
    """
    os.environ.setdefault("LC_ALL", "C.UTF-8")
    os.environ.setdefault("LANG", "C.UTF-8")
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")


class WhisperTranscriber(Transcriber):
    def __init__(self, config: dict[str, Any] | None = None):
        cfg = config or {}
        self.model_name: str = cfg.get("model", "large-v3-turbo")
        self.device: str = cfg.get("device", "cpu")
        self.compute_type: str = cfg.get("compute_type", "int8")
        self.beam_size: int = cfg.get("beam_size", 5)
        self.vad_filter: bool = cfg.get("vad_filter", True)
        # Permite user desabilitar guards via config (debug)
        self.condition_on_previous_text: bool = cfg.get("condition_on_previous_text", False)
        self.compression_ratio_threshold: float = cfg.get("compression_ratio_threshold", 2.4)
        self.log_prob_threshold: float = cfg.get("log_prob_threshold", -1.0)
        self.no_speech_threshold: float = cfg.get("no_speech_threshold", 0.6)
        self.initial_prompt: str | None = cfg.get("initial_prompt")  # opcional pt-BR
        self._model = None  # carrega no transcribe (lazy)

    @property
    def name(self) -> str:
        return f"whisper-{self.model_name}"

    def _load_model(self):
        if self._model is not None:
            return self._model
        _ensure_utf8_locale()
        from faster_whisper import WhisperModel  # type: ignore[import-not-found]

        log.info(
            "carregando Whisper '%s' device=%s compute=%s",
            self.model_name,
            self.device,
            self.compute_type,
        )
        self._model = WhisperModel(
            self.model_name,
            device=self.device,
            compute_type=self.compute_type,
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
            # Anti-hallucination guards:
            condition_on_previous_text=self.condition_on_previous_text,
            temperature=_TEMPERATURE_FALLBACK,
            compression_ratio_threshold=self.compression_ratio_threshold,
            log_prob_threshold=self.log_prob_threshold,
            no_speech_threshold=self.no_speech_threshold,
            initial_prompt=self.initial_prompt,
        )

        segments = [TranscriptionSegment(start=s.start, end=s.end, text=s.text) for s in seg_iter]
        log.info(
            "whisper: %d segmentos, idioma=%s prob=%.2f",
            len(segments),
            info.language,
            info.language_probability,
        )
        return TranscriptionResult(
            segments=segments,
            language=info.language,
            language_probability=info.language_probability,
            backend=self.name,
        )
