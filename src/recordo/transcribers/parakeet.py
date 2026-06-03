"""ParakeetTranscriber — NVIDIA NeMo Parakeet-TDT-0.6B-v3 (opt-in).

Risco conhecido: treinado em Português Europeu (pt-PT), não pt-BR.
Pode introduzir lexicalmente palavras como "comboio" (trem) e "autocarro" (ônibus).
Use com cautela em reuniões pt-BR. Instalação via setup.sh --with-parakeet.

Áudio deve ser 16kHz mono. Conversão automática via ffmpeg se necessário.

v0.2.3 — chunking para áudios longos (evita OOM):
  Áudios maiores que `chunk_seconds` (default 600s = 10min) são processados
  em pedaços com overlap mínimo, com GC entre chunks. Resultados mesclados
  com offsets ajustados.
"""

from __future__ import annotations

import gc
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
        # v0.2.3: chunking config (evita OOM em áudios longos)
        self.chunk_seconds: int = int(cfg.get("chunk_seconds", 600))
        self.chunk_overlap: float = float(cfg.get("chunk_overlap_seconds", 2.0))
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

    @staticmethod
    def _probe_duration(audio: Path) -> float:
        """Retorna duração em segundos via ffprobe. Retorna 0 se falhar."""
        if not shutil.which("ffprobe"):
            return 0.0
        try:
            r = subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "default=nw=1:nk=1",
                    str(audio),
                ],
                capture_output=True,
                text=True,
                check=True,
                timeout=15,
            )
            return float(r.stdout.strip() or 0)
        except (subprocess.SubprocessError, ValueError):
            return 0.0

    def _ensure_wav16k(self, audio: Path, *, start: float = 0.0, duration: float | None = None) -> Path:
        """Converte qualquer formato pra wav 16kHz mono.

        v0.2.3: aceita start/duration para chunking (extrai só pedaço do áudio).
        """
        if audio.suffix == ".wav" and start == 0.0 and duration is None:
            log.warning(
                "audio já é .wav mas convertemos pra 16kHz mono mesmo assim "
                "(Parakeet exige formato fixo) — overhead inevitável"
            )
        if not shutil.which("ffmpeg"):
            raise RuntimeError("ffmpeg necessário pra Parakeet (conversão pra 16kHz wav)")

        tmp_wav = Path(tempfile.mkstemp(suffix=".wav", prefix="recordo-parakeet-")[1])
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error"]
        if start > 0:
            cmd += ["-ss", f"{start:.3f}"]
        cmd += ["-i", str(audio)]
        if duration is not None and duration > 0:
            cmd += ["-t", f"{duration:.3f}"]
        cmd += ["-ac", "1", "-ar", "16000", "-y", str(tmp_wav)]

        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as e:
            tmp_wav.unlink(missing_ok=True)
            raise RuntimeError(f"falha ffmpeg conversão: {e.stderr}") from e
        return tmp_wav

    def _transcribe_chunk(self, model, wav: Path, *, time_offset: float) -> list[TranscriptionSegment]:
        """Transcreve 1 chunk; ajusta timestamps com time_offset; libera GC."""
        try:
            output = model.transcribe([str(wav)], timestamps=True)
        finally:
            wav.unlink(missing_ok=True)

        hyp = output[0] if output else None
        if not hyp:
            return []

        segments: list[TranscriptionSegment] = []
        ts = getattr(hyp, "timestamp", None)
        if ts and "segment" in ts:
            for seg in ts["segment"]:
                segments.append(
                    TranscriptionSegment(
                        start=float(seg.get("start", 0)) + time_offset,
                        end=float(seg.get("end", 0)) + time_offset,
                        text=str(seg.get("segment", seg.get("text", ""))),
                    ),
                )
        elif hasattr(hyp, "text"):
            segments.append(TranscriptionSegment(start=time_offset, end=time_offset, text=str(hyp.text)))

        # Liberar memória entre chunks (Lhotse CutSet acumula RAM)
        del output, hyp
        gc.collect()
        return segments

    def transcribe(self, audio: Path, *, language: str = "pt") -> TranscriptionResult:
        model = self._load_model()
        log.info("transcrevendo %s (parakeet)", audio.name)

        # v0.2.3: detectar duração para decidir chunking
        duration = self._probe_duration(audio)
        if duration <= 0 or duration <= self.chunk_seconds:
            # Caso simples: arquivo curto, sem chunking
            wav = self._ensure_wav16k(audio)
            segments = self._transcribe_chunk(model, wav, time_offset=0.0)
        else:
            # Áudio longo: chunking obrigatório (senão OOM)
            n_chunks = int(duration // self.chunk_seconds) + (1 if duration % self.chunk_seconds > 0 else 0)
            log.info(
                "áudio longo (%.1fs > %ds): processando em %d chunks",
                duration,
                self.chunk_seconds,
                n_chunks,
            )
            segments = []
            for i in range(n_chunks):
                start = i * self.chunk_seconds
                # último chunk vai até o fim; outros incluem overlap pequeno
                if i == n_chunks - 1:
                    chunk_dur = duration - start
                else:
                    chunk_dur = self.chunk_seconds + self.chunk_overlap
                log.info(
                    "chunk %d/%d: start=%.1fs dur=%.1fs",
                    i + 1,
                    n_chunks,
                    start,
                    chunk_dur,
                )
                wav = self._ensure_wav16k(audio, start=start, duration=chunk_dur)
                chunk_segs = self._transcribe_chunk(model, wav, time_offset=start)
                segments.extend(chunk_segs)
                log.info("chunk %d concluído: +%d segmentos", i + 1, len(chunk_segs))

        log.info("parakeet: %d segmentos totais", len(segments))
        return TranscriptionResult(
            segments=segments,
            language=language,
            language_probability=1.0,
            backend=self.name,
        )
