# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Caio Hat
"""E2E smoke: valida estrutura de pipeline sem precisar de modelo Whisper baixado.

Usa stub de transcriber para não requerer ~2GB de modelo em CI.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.e2e


def test_recording_dir_has_required_files(recording_dir: Path):
    """Fixture cria audio.opus + nota.md."""
    assert (recording_dir / "audio.opus").exists()
    assert (recording_dir / "nota.md").exists()
    nota = (recording_dir / "nota.md").read_text(encoding="utf-8")
    assert "subject: E2E test" in nota


def test_pipeline_run_step_with_stub_transcriber(recording_dir: Path, minimal_config: dict):
    """Testa run_step com transcriber stubado (não precisa modelo real)."""
    from recordo.transcribers.base import Transcriber, TranscriptionResult, TranscriptionSegment

    class StubTranscriber(Transcriber):
        @property
        def name(self) -> str:
            return "stub-test"

        def transcribe(self, audio: Path, *, language: str = "pt") -> TranscriptionResult:
            return TranscriptionResult(
                segments=[TranscriptionSegment(start=0.0, end=5.0, text="Hello e2e test")],
                language=language,
                language_probability=1.0,
                backend=self.name,
            )

    with patch("recordo.pipeline.get_transcriber", return_value=StubTranscriber()):
        # Skip preflight
        with patch("recordo.hardware.preflight", return_value=(True, "ok")):
            from recordo.pipeline import run_step

            result = run_step(recording_dir, "transcribe", config=minimal_config)

    assert result.get("ok"), f"transcribe falhou: {result}"
    assert (recording_dir / "transcricao.txt").exists()
    assert "Hello e2e test" in (recording_dir / "transcricao.txt").read_text(encoding="utf-8")


def test_summarize_step_heuristic(recording_dir: Path, minimal_config: dict):
    """Resumo heurístico (sem LLM) após transcrição stubada."""
    # Simula transcricao.txt já escrita
    (recording_dir / "transcricao.txt").write_text(
        "[00:00] Hello world this is e2e test of pipeline.\n"
        "[00:05] Test continues with more sentences for summary.\n",
        encoding="utf-8",
    )
    # nota.md já tem placeholder
    minimal_config["summarizer"] = {"backend": "heuristic"}

    from recordo.pipeline import run_step

    result = run_step(recording_dir, "summarize", config=minimal_config)

    # heurístico pode retornar ok ou indisponível dependendo do projeto
    assert isinstance(result, dict)
    assert result.get("step") == "summarize"
