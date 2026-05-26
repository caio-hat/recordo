"""Tests do post_pipeline com filesystem mockado.

Cobre:
  - Move áudio cross-fs com warning vs same-fs silencioso
  - Cria target_dir com YYYY-MM-DD_safe_subject
  - Renderiza nota.md com frontmatter + marks + placeholder
  - Spawn de thread de transcrição (mockada — não baixa modelo)
"""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from recordo import pipeline as pipeline_mod
from recordo.pipeline import _safe_move, post_pipeline
from recordo.recorder import Mark, SessionState


@pytest.fixture
def session_state(tmp_path: Path) -> SessionState:
    src = tmp_path / "recordings" / "Test_20260101_120000"
    src.mkdir(parents=True)
    state = SessionState(
        subject="Test Subject",
        session_id="20260101_120000",
        started_at="2026-01-01T12:00:00",
        output_dir=str(src),
        mic_source="alsa_input.test",
        sys_source="alsa_output.test.monitor",
        codec="opus",
        bitrate="32k",
        layout="merge",
    )
    return state


@pytest.fixture
def final_audio(session_state, tmp_path: Path) -> Path:
    audio = Path(session_state.output_dir) / "Test_Subject_20260101_120000.opus"
    audio.write_bytes(b"\x00" * 1024)
    # Também cria um *_report.md
    (Path(session_state.output_dir) / "20260101_120000_report.md").write_text(
        "# Relatório",
        encoding="utf-8",
    )
    return audio


@pytest.fixture
def notas_dir(tmp_path: Path, monkeypatch) -> Path:
    """Redireciona NOTAS_DIR pra dentro de tmp_path."""
    notas = tmp_path / "Notas"
    monkeypatch.setattr(pipeline_mod, "NOTAS_DIR", notas)
    return notas


@pytest.fixture
def no_transcribe(monkeypatch):
    """Substitui _transcribe_async por no-op pra evitar baixar modelo."""
    monkeypatch.setattr(pipeline_mod, "_transcribe_async", lambda *a, **kw: None)


class TestSafeMove:
    def test_same_fs_no_warning(self, tmp_path: Path, caplog):
        src = tmp_path / "src.bin"
        dst = tmp_path / "dst.bin"
        src.write_bytes(b"data")

        with caplog.at_level(logging.WARNING):
            _safe_move(src, dst)

        assert dst.exists()
        assert not src.exists()
        # Sem warning de cross-fs
        assert not any("cross-filesystem" in r.message for r in caplog.records)

    def test_cross_fs_logs_warning(self, tmp_path: Path, caplog, monkeypatch):
        src = tmp_path / "src.bin"
        dst_dir = tmp_path / "other"
        dst_dir.mkdir()
        src.write_bytes(b"data" * 1024)

        # Em vez de mockar Path.stat (que entra em recursão pelo is_dir),
        # mockamos shutil.move pra confirmar que o warning sai antes de mover.
        # E forçamos st_dev distinto via os.stat patching.
        import os

        real_os_stat = os.stat

        def fake_os_stat(path, *a, **kw):
            r = real_os_stat(path, *a, **kw)

            # Faz um stat_result-like com st_dev custom só pros paths de teste
            class S:
                def __init__(self, base, dev):
                    self._base = base
                    self.st_dev = dev

                def __getattr__(self, name):
                    return getattr(self._base, name)

            p = str(path)
            if p == str(src):
                return S(r, 1)
            if p == str(dst_dir):
                return S(r, 2)
            return r

        monkeypatch.setattr(os, "stat", fake_os_stat)

        with caplog.at_level(logging.WARNING):
            _safe_move(src, dst_dir / "dst.bin")

        assert any("cross-filesystem" in r.message for r in caplog.records)

    def test_missing_src_raises(self, tmp_path: Path):
        # _safe_move ignora FileNotFoundError no STAT mas shutil.move falha
        with pytest.raises(FileNotFoundError):
            _safe_move(tmp_path / "nope.bin", tmp_path / "dst.bin")


class TestPostPipeline:
    def test_creates_target_dir_with_date_and_safe_subject(
        self,
        session_state,
        final_audio,
        notas_dir,
        no_transcribe,
    ):
        target = post_pipeline(session_state, final_audio, [])
        assert target is not None
        assert target.parent == notas_dir
        # Subject "Test Subject" → safe_subject → Test_Subject
        assert "2026-01-01" in target.name
        assert "Test" in target.name

    def test_moves_audio_and_renames(
        self,
        session_state,
        final_audio,
        notas_dir,
        no_transcribe,
    ):
        target = post_pipeline(session_state, final_audio, [])
        assert (target / "audio.opus").exists()
        assert not final_audio.exists()  # foi movido

    def test_moves_report_md(
        self,
        session_state,
        final_audio,
        notas_dir,
        no_transcribe,
    ):
        target = post_pipeline(session_state, final_audio, [])
        reports = list(target.glob("*_report.md"))
        assert len(reports) == 1
        assert "20260101_120000" in reports[0].name

    def test_renders_nota_md_with_frontmatter(
        self,
        session_state,
        final_audio,
        notas_dir,
        no_transcribe,
    ):
        target = post_pipeline(session_state, final_audio, [])
        nota = (target / "nota.md").read_text(encoding="utf-8")
        assert "subject: Test Subject" in nota
        assert "audio: ./audio.opus" in nota
        assert "auto_started: False" in nota
        assert "_(processando" in nota  # placeholder

    def test_renders_marks_in_nota_md(
        self,
        session_state,
        final_audio,
        notas_dir,
        no_transcribe,
    ):
        marks = [
            Mark(ts_seconds=125.5, iso_time="2026-01-01T12:02:05", text="decisão X"),
            Mark(ts_seconds=300.0, iso_time="2026-01-01T12:05:00", text=""),
        ]
        target = post_pipeline(session_state, final_audio, marks)
        nota = (target / "nota.md").read_text(encoding="utf-8")
        assert "[00:02:05] decisão X" in nota
        assert "(marca)" in nota  # marca sem texto

    def test_returns_none_when_audio_missing(
        self,
        session_state,
        notas_dir,
        no_transcribe,
    ):
        missing = Path("/tmp/recordo-test-does-not-exist.opus")
        target = post_pipeline(session_state, missing, [])
        assert target is None

    def test_uses_custom_config_backend(
        self,
        session_state,
        final_audio,
        notas_dir,
        no_transcribe,
    ):
        cfg = {
            "transcriber": {
                "backend": "parakeet",
                "language": "pt",
                "parakeet": {"model": "fake/parakeet"},
            },
        }
        target = post_pipeline(session_state, final_audio, [], config=cfg)
        nota = (target / "nota.md").read_text(encoding="utf-8")
        assert "backend: parakeet" in nota

    def test_spawns_transcribe_thread(
        self,
        session_state,
        final_audio,
        notas_dir,
        monkeypatch,
    ):
        """Confirma que post_pipeline dispara thread de transcrição."""
        called: list[tuple] = []

        def fake_transcribe_async(*args, **kwargs):
            called.append((args, kwargs))

        monkeypatch.setattr(pipeline_mod, "_transcribe_async", fake_transcribe_async)

        # Patch threading.Thread pra capturar antes de spawn
        with patch.object(pipeline_mod.threading, "Thread") as MockThread:
            mock_thread = MagicMock()
            MockThread.return_value = mock_thread
            post_pipeline(session_state, final_audio, [])
            assert MockThread.called
            mock_thread.start.assert_called_once()
