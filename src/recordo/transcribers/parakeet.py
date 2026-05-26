"""ParakeetTranscriber — NVIDIA NeMo Parakeet-TDT-0.6B-v3 (opt-in).

Risco conhecido: treinado em Português Europeu (pt-PT), não pt-BR.
Pode introduzir lexicalmente palavras como "comboio" (trem) e "autocarro" (ônibus).
Use com cautela em reuniões pt-BR. Instalação via setup.sh --with-parakeet.

Áudio deve ser 16kHz mono. Conversão automática via ffmpeg se necessário.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from .base import Transcriber, TranscriptionResult, TranscriptionSegment

log = logging.getLogger(__name__)


class ParakeetTranscriber(Transcriber):
    def __init__(self, config: dict[str, Any] | None = None):
        cfg = config or {}
        self.model_name: str = cfg.get("model", "nvidia/parakeet-tdt-0.6b-v3")
        self.use_onnx: bool = cfg.get("use_onnx", False)
        self._model = None

    @property
    def name(self) -> str:
        suffix = "-onnx" if self.use_onnx else ""
        return f"parakeet-{self.model_name.split('/')[-1]}{suffix}"

    def _load_model(self):
        if self._model is not None:
            return self._model
        try:
            import nemo.collections.asr as nemo_asr  # type: ignore[import-not-found]
        except ImportError as e:
            raise RuntimeError(
                "Parakeet backend requer nemo_toolkit[asr]. Instale com: bash setup.sh --with-parakeet"
            ) from e

        log.info("carregando Parakeet '%s'", self.model_name)
        self._model = nemo_asr.models.ASRModel.from_pretrained(self.model_name)
        return self._model

    def _ensure_wav16k(self, audio: Path) -> Path:
        """Converte qualquer formato pra wav 16kHz mono se necessário."""
        if audio.suffix == ".wav":
            # ainda pode não estar em 16k mono; convertemos sempre por segurança
            pass
        if not shutil.which("ffmpeg"):
            raise RuntimeError("ffmpeg necessário pra Parakeet (conversão pra 16kHz wav)")

        tmp_wav = Path(tempfile.mkstemp(suffix=".wav", prefix="recordo-parakeet-")[1])
        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(audio),
            "-ac",
            "1",
            "-ar",
            "16000",  # mono 16kHz
            "-y",
            str(tmp_wav),
        ]
        log.info("convertendo %s → wav 16kHz mono", audio.name)
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as e:
            tmp_wav.unlink(missing_ok=True)
            raise RuntimeError(f"falha ffmpeg conversão: {e.stderr}") from e
        return tmp_wav

    def transcribe(self, audio: Path, *, language: str = "pt") -> TranscriptionResult:
        model = self._load_model()
        wav = self._ensure_wav16k(audio)
        log.info("transcrevendo %s (parakeet)", audio.name)

        try:
            output = model.transcribe([str(wav)], timestamps=True)
        finally:
            wav.unlink(missing_ok=True)

        # output[0] é um Hypothesis com timestamp dict
        hyp = output[0] if output else None
        if not hyp:
            return TranscriptionResult(language=language, backend=self.name)

        segments: list[TranscriptionSegment] = []
        ts = getattr(hyp, "timestamp", None)
        if ts and "segment" in ts:
            for seg in ts["segment"]:
                segments.append(
                    TranscriptionSegment(
                        start=float(seg.get("start", 0)),
                        end=float(seg.get("end", 0)),
                        text=str(seg.get("segment", seg.get("text", ""))),
                    ),
                )
        elif hasattr(hyp, "text"):
            # fallback: texto único sem timestamps
            segments.append(TranscriptionSegment(start=0.0, end=0.0, text=str(hyp.text)))

        log.info("parakeet: %d segmentos", len(segments))
        return TranscriptionResult(
            segments=segments,
            language=language,
            language_probability=1.0,  # parakeet não retorna prob
            backend=self.name,
        )
