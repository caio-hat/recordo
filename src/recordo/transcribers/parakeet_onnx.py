# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Caio Hat
"""ParakeetONNXTranscriber — sherpa-onnx based, ~2GB RAM peak."""

from __future__ import annotations

import gc
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from .base import Transcriber, TranscriptionResult, TranscriptionSegment

log = logging.getLogger(__name__)

DEFAULT_MODEL_ID = "istupakov/parakeet-tdt-0.6b-v3-onnx"


def _hf_cache_root() -> Path:
    return Path(os.environ.get("HF_HOME", os.path.expanduser("~/.cache/huggingface"))) / "hub"


def _resolve_model_dir(model_id: str = DEFAULT_MODEL_ID) -> Path | None:
    """Procura snapshot mais recente do modelo no cache HF."""
    repo_dir = _hf_cache_root() / f"models--{model_id.replace('/', '--')}"
    snap_dir = repo_dir / "snapshots"
    if not snap_dir.exists():
        return None
    snapshots = sorted(
        [d for d in snap_dir.iterdir() if d.is_dir()],
        key=lambda d: d.stat().st_mtime,
        reverse=True,
    )
    return snapshots[0] if snapshots else None


def is_installed(model_id: str = DEFAULT_MODEL_ID) -> bool:
    """Retorna True se modelo ONNX está no cache HF."""
    d = _resolve_model_dir(model_id)
    if d is None:
        return False
    has_encoder = any((d / f).exists() for f in ("encoder-model.int8.onnx", "encoder-model.onnx"))
    has_decoder = any(
        (d / f).exists()
        for f in (
            "decoder_joint-model.int8.onnx",
            "decoder_joint-model.onnx",
        )
    )
    has_tokens = (d / "tokens.txt").exists() or (d / "vocab.txt").exists()
    return has_encoder and has_decoder and has_tokens


class ParakeetONNXTranscriber(Transcriber):
    """NVIDIA Parakeet TDT 0.6B v3 via ONNX (sherpa-onnx)."""

    def __init__(self, config: dict[str, Any] | None = None):
        cfg = config or {}
        self.model_id: str = cfg.get("model", DEFAULT_MODEL_ID)
        self.num_threads: int = int(cfg.get("num_threads", 4))
        self.use_int8: bool = bool(cfg.get("use_int8", True))
        self._recognizer = None

    @property
    def name(self) -> str:
        suffix = "int8" if self.use_int8 else "fp32"
        return f"parakeet-onnx-{suffix}"

    def _load_recognizer(self):
        if self._recognizer is not None:
            return self._recognizer
        try:
            import sherpa_onnx  # type: ignore[import-untyped]
        except ImportError as e:
            raise RuntimeError("sherpa-onnx não instalado. Instale com: pip install sherpa-onnx") from e

        model_dir = _resolve_model_dir(self.model_id)
        if model_dir is None:
            raise RuntimeError(
                f"modelo Parakeet ONNX não encontrado em "
                f"{_hf_cache_root()}. "
                "Abra Modelos no app e baixe o modelo."
            )

        if self.use_int8 and (model_dir / "encoder-model.int8.onnx").exists():
            encoder = model_dir / "encoder-model.int8.onnx"
            decoder = model_dir / "decoder_joint-model.int8.onnx"
        else:
            encoder = model_dir / "encoder-model.onnx"
            decoder = model_dir / "decoder_joint-model.onnx"
        tokens = model_dir / "tokens.txt"
        if not tokens.exists():
            tokens = model_dir / "vocab.txt"
        for p in (encoder, decoder, tokens):
            if not p.exists():
                raise RuntimeError(f"arquivo do modelo ausente: {p}")

        log.info(
            "carregando Parakeet ONNX %s (encoder=%s)",
            self.model_id,
            encoder.name,
        )
        self._recognizer = sherpa_onnx.OfflineRecognizer.from_transducer(
            encoder=str(encoder),
            decoder=str(decoder),
            joiner="",
            tokens=str(tokens),
            num_threads=self.num_threads,
            sample_rate=16000,
            feature_dim=128,
            decoding_method="greedy_search",
            model_type="transducer",
        )
        return self._recognizer

    @staticmethod
    def _ensure_wav16k(audio: Path) -> Path:
        """Convert qualquer formato → wav 16kHz mono via ffmpeg."""
        if not shutil.which("ffmpeg"):
            raise RuntimeError("ffmpeg necessário para converter áudio")
        tmp_wav = Path(tempfile.mkstemp(suffix=".wav", prefix="recordo-onnx-")[1])
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
            "16000",
            "-y",
            str(tmp_wav),
        ]
        try:
            subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except subprocess.CalledProcessError as e:
            tmp_wav.unlink(missing_ok=True)
            raise RuntimeError(f"ffmpeg falhou: {e.stderr}") from e
        return tmp_wav

    @staticmethod
    def _read_wav_samples(wav: Path) -> tuple[list[float], int]:
        """Lê WAV 16kHz mono PCM → floats [-1, 1] + sample_rate."""
        import wave

        import numpy as np  # type: ignore[import-untyped]

        with wave.open(str(wav), "rb") as w:
            sr = w.getframerate()
            n = w.getnframes()
            raw = w.readframes(n)
        samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        return samples.tolist(), sr

    def transcribe(self, audio: Path, *, language: str = "pt") -> TranscriptionResult:
        recognizer = self._load_recognizer()
        wav = self._ensure_wav16k(audio)
        try:
            log.info("transcrevendo %s (parakeet-onnx)", audio.name)
            samples, sr = self._read_wav_samples(wav)
            stream = recognizer.create_stream()
            stream.accept_waveform(sr, samples)
            recognizer.decode_stream(stream)
            result = stream.result
        finally:
            wav.unlink(missing_ok=True)
            gc.collect()

        full_text = (result.text or "").strip()
        timestamps = result.timestamps or []
        tokens = result.tokens or []

        segments: list[TranscriptionSegment] = []
        if tokens and timestamps and len(tokens) == len(timestamps):
            cur_start = 0.0
            cur_text_parts: list[str] = []
            cur_t = 0.0
            for tok, t in zip(tokens, timestamps, strict=False):
                if not cur_text_parts:
                    cur_start = t
                cur_text_parts.append(tok)
                cur_t = t
                if t - cur_start >= 10.0 and tok.endswith((".", "!", "?", "…", ",")):
                    seg_text = " ".join(cur_text_parts).replace(" ▁", "").replace("▁", " ").strip()
                    if seg_text:
                        segments.append(
                            TranscriptionSegment(
                                start=cur_start,
                                end=cur_t,
                                text=seg_text,
                            )
                        )
                    cur_text_parts = []
            if cur_text_parts:
                seg_text = " ".join(cur_text_parts).replace(" ▁", "").replace("▁", " ").strip()
                if seg_text:
                    segments.append(
                        TranscriptionSegment(
                            start=cur_start,
                            end=cur_t,
                            text=seg_text,
                        )
                    )
        elif full_text:
            segments.append(TranscriptionSegment(start=0.0, end=0.0, text=full_text))

        log.info("parakeet-onnx: %d segmentos", len(segments))
        return TranscriptionResult(
            segments=segments,
            language=language,
            language_probability=1.0,
            backend=self.name,
        )
