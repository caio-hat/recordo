# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Caio Hat
"""E2E test fixtures."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


def _has_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None


requires_ffmpeg = pytest.mark.skipif(not _has_ffmpeg(), reason="ffmpeg não disponível")


@pytest.fixture
def silence_audio(tmp_path: Path) -> Path:
    """Gera audio.opus com 10s de silêncio para testes que não precisam de fala real."""
    audio = tmp_path / "audio.opus"
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        "anullsrc=channel_layout=mono:sample_rate=16000",
        "-t",
        "10",
        "-c:a",
        "libopus",
        "-b:a",
        "32k",
        "-y",
        str(audio),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        pytest.skip(f"ffmpeg falhou ao gerar silêncio: {r.stderr[:200]}")
    return audio


@pytest.fixture
def recording_dir(tmp_path: Path, silence_audio: Path) -> Path:
    """Diretório de gravação mínimo: audio.opus + nota.md placeholder."""
    rec = tmp_path / "2026-06-01_e2e_test"
    rec.mkdir()
    shutil.copy(silence_audio, rec / "audio.opus")
    (rec / "nota.md").write_text(
        "---\nsubject: E2E test\ndate: 2026-06-01T00:00:00\n"
        "duration_min: 0.16\nbackend: pending\nsegments: 0\n---\n\n"
        "# E2E Test\n\n## Transcrição\n\n[transcrição pendente]\n",
        encoding="utf-8",
    )
    return rec


@pytest.fixture
def minimal_config(tmp_path: Path, monkeypatch) -> dict:
    """Config mínima isolada (NOTAS_DIR fora de ~)."""
    notas_dir = tmp_path / "notas-e2e"
    notas_dir.mkdir()
    monkeypatch.setenv("RECORDO_NOTAS_DIR", str(notas_dir))
    from recordo.config import load_config

    cfg = load_config()
    cfg["transcriber"] = {
        "backend": "whisper",
        "language": "pt",
        "whisper": {"model": "tiny", "device": "cpu", "compute_type": "int8", "initial_prompt": ""},
        "parakeet": {
            "engine": "onnx",
            "model": "istupakov/parakeet-tdt-0.6b-v3-onnx",
            "use_int8": True,
            "num_threads": 4,
        },
        "cohere": {
            "model": "cohere-transcribe-03-2026",
            "api_key_env": "COHERE_API_KEY",
            "timeout_seconds": 300,
        },
    }
    cfg["summarizer"] = {"backend": "heuristic"}
    return cfg
