"""CohereTranscriber — Cohere Transcribe via API HTTP.

Cohere Transcribe (lançado 26/março/2026):
  - 2B parâmetros, dedicated ASR
  - #1 Open ASR Leaderboard (WER médio 5.42%)
  - 3x mais rápido que Whisper Large-v3 / Parakeet
  - Apache 2.0 (permite auto-host)
  - 14 idiomas: EN, DE, FR, IT, ES, **PT**, EL, NL, PL, VI, ZH, AR, JA, KO

Esta implementação usa a **API REST oficial** da Cohere (free tier com rate
limits). Para auto-host, usar `CohereLabs/cohere-transcribe-03-2026` no HF
Transformers (não implementado aqui — ~12GB de download).

Limitações da API:
  - Max 25MB por request → faz chunking automático em segmentos de ~20min
    (Opus 32k voz: ~20MB por 20min) com offset de timestamps
  - Suporta: flac, mp3, mpeg, mpga, ogg, wav (Opus precisa converter)
  - Rate limit no trial; produção via Model Vault (pago)

Auth:
  api_key = config.api_key OU env COHERE_API_KEY (default)
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .base import Transcriber, TranscriptionResult, TranscriptionSegment

log = logging.getLogger(__name__)

DEFAULT_MODEL = "cohere-transcribe-03-2026"
API_ENDPOINT = "https://api.cohere.com/v2/audio/transcriptions"

# Limite de upload da API: 25MB. Usamos 20MB para deixar margem do header
# multipart e segurança contra arredondamento.
MAX_UPLOAD_BYTES = 20 * 1024 * 1024

# Quando precisamos chunking, dividimos o áudio em pedaços de N segundos.
# 20min de Opus 32k = ~5MB; convertendo pra wav 16k mono = ~38MB → não cabe.
# 10min de wav 16k mono = ~19MB → cabe direto.
DEFAULT_CHUNK_SECONDS = 600  # 10 minutos


class CohereTranscriber(Transcriber):
    def __init__(self, config: dict[str, Any] | None = None):
        cfg = config or {}
        self.model_name: str = cfg.get("model", DEFAULT_MODEL)
        self.api_key: str = self._resolve_api_key(cfg)
        self.timeout: int = cfg.get("timeout_seconds", 300)
        self.chunk_seconds: int = cfg.get("chunk_seconds", DEFAULT_CHUNK_SECONDS)
        self.endpoint: str = cfg.get("endpoint", API_ENDPOINT)

    @staticmethod
    def _resolve_api_key(cfg: dict[str, Any]) -> str:
        if direct := cfg.get("api_key"):
            return str(direct).strip()
        env_var = cfg.get("api_key_env", "COHERE_API_KEY")
        return os.environ.get(env_var, "").strip()

    @property
    def name(self) -> str:
        return f"cohere-{self.model_name}"

    def transcribe(self, audio: Path, *, language: str = "pt") -> TranscriptionResult:
        if not self.api_key:
            raise RuntimeError(
                "Cohere API key não configurada. Defina COHERE_API_KEY no env "
                "OU [transcriber.cohere].api_key no config.toml. "
                "Get key: https://dashboard.cohere.com/api-keys"
            )
        if not shutil.which("ffmpeg"):
            raise RuntimeError("ffmpeg necessário para conversão de áudio")

        # Cohere aceita wav/mp3/flac/ogg, mas mp3 dá menor footprint → converte
        # sempre para 16kHz mono (formato canônico ASR) que é menor que opus
        # original quando >10min, e perfeito para a Cohere processar.
        log.info("[%s] convertendo %s → wav 16kHz mono", self.name, audio.name)
        wav_path = self._convert_to_wav(audio)

        try:
            size = wav_path.stat().st_size
            if size <= MAX_UPLOAD_BYTES:
                log.info("[%s] upload single (%.1fMB)", self.name, size / 1024 / 1024)
                segments = self._transcribe_single(wav_path, language=language, time_offset=0.0)
            else:
                log.info(
                    "[%s] áudio %.1fMB > 20MB → chunking em pedaços de %ds",
                    self.name,
                    size / 1024 / 1024,
                    self.chunk_seconds,
                )
                segments = self._transcribe_chunked(wav_path, language=language)

            return TranscriptionResult(
                segments=segments,
                language=language,
                language_probability=1.0,  # Cohere não retorna prob
                backend=self.name,
            )
        finally:
            wav_path.unlink(missing_ok=True)

    def _convert_to_wav(self, audio: Path) -> Path:
        """Converte qualquer áudio para wav 16kHz mono PCM s16le."""
        tmp_wav = Path(tempfile.mkstemp(suffix=".wav", prefix="recordo-cohere-")[1])
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
            subprocess.run(cmd, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as e:
            tmp_wav.unlink(missing_ok=True)
            raise RuntimeError(f"ffmpeg conversion failed: {e.stderr}") from e
        return tmp_wav

    def _transcribe_single(
        self, wav_path: Path, *, language: str, time_offset: float
    ) -> list[TranscriptionSegment]:
        """Single upload — área <20MB."""
        text = self._upload_and_get_text(wav_path, language=language)
        if not text.strip():
            return []

        # Cohere API atual retorna apenas `text` sem timestamps por segment.
        # Reconstruímos um único TranscriptionSegment cobrindo o chunk inteiro,
        # com duration computada via ffprobe.
        duration = _ffprobe_duration(wav_path) or 0.0
        return [
            TranscriptionSegment(
                start=time_offset,
                end=time_offset + duration,
                text=text.strip(),
            )
        ]

    def _transcribe_chunked(self, wav_path: Path, *, language: str) -> list[TranscriptionSegment]:
        """Divide wav em chunks de N segundos com ffmpeg, transcreve cada um."""
        all_segments: list[TranscriptionSegment] = []
        total_duration = _ffprobe_duration(wav_path) or 0.0
        n_chunks = int(total_duration // self.chunk_seconds) + 1

        log.info(
            "[%s] %d chunks x %ds = %.0fs total",
            self.name,
            n_chunks,
            self.chunk_seconds,
            total_duration,
        )

        for i in range(n_chunks):
            start = i * self.chunk_seconds
            if start >= total_duration:
                break
            chunk_path = Path(tempfile.mkstemp(suffix=f"-chunk{i:02d}.wav", prefix="recordo-cohere-")[1])
            try:
                # Extrai chunk com ffmpeg (-ss seek + -t duration)
                cmd = [
                    "ffmpeg",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-ss",
                    str(start),
                    "-i",
                    str(wav_path),
                    "-t",
                    str(self.chunk_seconds),
                    "-c",
                    "copy",  # já é wav PCM, copy é instantâneo
                    "-y",
                    str(chunk_path),
                ]
                subprocess.run(cmd, check=True, capture_output=True, text=True)
                if chunk_path.stat().st_size < 1024:
                    log.warning("chunk %d vazio, pulando", i)
                    continue

                log.info(
                    "[%s] chunk %d/%d (%.1fMB) — transcrevendo",
                    self.name,
                    i + 1,
                    n_chunks,
                    chunk_path.stat().st_size / 1024 / 1024,
                )
                segs = self._transcribe_single(chunk_path, language=language, time_offset=float(start))
                all_segments.extend(segs)
            except subprocess.CalledProcessError as e:
                log.error("chunk %d falhou: %s", i, e.stderr)
            finally:
                chunk_path.unlink(missing_ok=True)

        return all_segments

    def _upload_and_get_text(self, wav_path: Path, *, language: str) -> str:
        """Multipart POST para /v2/audio/transcriptions."""
        boundary = "----RecordoBoundary7MA4YWxkTrZu0gW"

        # Construir body multipart manualmente (urllib não tem helper nativo)
        body_parts = [
            f"--{boundary}",
            'Content-Disposition: form-data; name="model"',
            "",
            self.model_name,
            f"--{boundary}",
            'Content-Disposition: form-data; name="language"',
            "",
            language,
            f"--{boundary}",
            f'Content-Disposition: form-data; name="file"; filename="{wav_path.name}"',
            "Content-Type: audio/wav",
            "",
        ]
        prefix = "\r\n".join(body_parts).encode("utf-8") + b"\r\n"
        suffix = f"\r\n--{boundary}--\r\n".encode()
        with wav_path.open("rb") as f:
            audio_bytes = f.read()
        body = prefix + audio_bytes + suffix

        req = Request(
            self.endpoint,
            data=body,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            },
            method="POST",
        )
        try:
            with urlopen(req, timeout=self.timeout) as resp:
                response_body = resp.read().decode("utf-8")
        except HTTPError as e:
            err_body = ""
            try:
                err_body = e.read().decode("utf-8", errors="ignore")[:500]
            except Exception:
                pass
            raise RuntimeError(f"Cohere API HTTP {e.code}: {e.reason}\n{err_body}") from e
        except (URLError, TimeoutError) as e:
            raise RuntimeError(f"Cohere API erro de rede: {e}") from e

        try:
            data = json.loads(response_body)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"Cohere API JSON inválido: {response_body[:300]}") from e

        return str(data.get("text", "")).strip()


def _ffprobe_duration(path: Path) -> float | None:
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
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
        return float(r.stdout.strip())
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError, FileNotFoundError):
        return None
