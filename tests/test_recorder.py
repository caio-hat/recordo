"""Tests do ciclo Recorder com subprocess mockado.

Estratégia: mockar subprocess.Popen e subprocess.run em ffmpeg_cmds via
monkeypatch. As funções `_merge` e `finalize` chamam subprocess.run; o
`start_segment` chama subprocess.Popen. Como o Recorder lê tamanho de
arquivo pra decidir status (merged/empty), criamos arquivos sintéticos
no path do segmento.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from recordo import recorder as recorder_mod
from recordo.recorder import Recorder, SessionState


@pytest.fixture
def session_state(tmp_path: Path) -> SessionState:
    return SessionState(
        subject="Test",
        session_id="20260101_120000",
        started_at="2026-01-01T12:00:00",
        output_dir=str(tmp_path),
        mic_source="alsa_input.test",
        sys_source="alsa_output.test.monitor",
        codec="opus",
        bitrate="32k",
        layout="merge",
    )


@pytest.fixture
def fake_ffmpeg(monkeypatch):
    """Mocka subprocess.Popen e subprocess.run pra simular ffmpeg.

    Popen retorna um MagicMock que simula proc vivo + saída via SIGINT.
    `subprocess.run` (usado em _merge e finalize) cria o arquivo de saída.
    """
    proc_mocks: list[MagicMock] = []

    def fake_popen(cmd, **_kwargs):
        m = MagicMock(spec=subprocess.Popen)
        m.pid = 12345 + len(proc_mocks)
        m._alive = True
        m.poll = MagicMock(side_effect=lambda: None if m._alive else 0)
        m.send_signal = MagicMock(side_effect=lambda *_a: setattr(m, "_alive", False))
        m.terminate = MagicMock(side_effect=lambda: setattr(m, "_alive", False))
        m.kill = MagicMock(side_effect=lambda: setattr(m, "_alive", False))
        m.wait = MagicMock(return_value=0)
        # Cria arquivos de saída fakes (último arg do cmd)
        out_path = Path(cmd[-1])
        out_path.write_bytes(b"\x00" * 256)  # opus fake
        proc_mocks.append(m)
        return m

    def fake_run(cmd, **kwargs):
        # Cria arquivo de output (último arg) — usado em _merge e finalize
        out_path = Path(cmd[-1])
        out_path.write_bytes(b"\x00" * 512)
        result = MagicMock()
        result.returncode = 0
        result.stderr = ""
        result.stdout = ""
        return result

    monkeypatch.setattr(recorder_mod.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(recorder_mod.subprocess, "run", fake_run)
    return proc_mocks


class TestRecorderLifecycle:
    def test_start_segment_spawns_two_ffmpegs(self, session_state, fake_ffmpeg):
        rec = Recorder(session_state, max_segment=1800, layout="merge")
        rec.start_segment()
        assert rec.recording is True
        assert rec.proc_sys is not None
        assert rec.proc_mic is not None
        assert rec.current is not None
        assert rec.current.index == 0
        # Os dois arquivos seg000_*.opus foram criados
        assert Path(rec.current.sys_file).exists()
        assert Path(rec.current.mic_file).exists()
        assert len(fake_ffmpeg) == 2

    def test_start_segment_idempotent_when_already_recording(
        self,
        session_state,
        fake_ffmpeg,
    ):
        rec = Recorder(session_state, max_segment=1800, layout="merge")
        rec.start_segment()
        rec.start_segment()  # no-op
        assert len(fake_ffmpeg) == 2  # não dobrou

    def test_stop_segment_terminates_and_merges(self, session_state, fake_ffmpeg):
        rec = Recorder(session_state, max_segment=1800, layout="merge")
        rec.start_segment()
        seg = rec.stop_segment()
        assert seg is not None
        assert rec.recording is False
        assert seg.status == "merged"
        assert seg.size_bytes > 0
        # Sinal SIGINT enviado a ambos
        for p in fake_ffmpeg:
            p.send_signal.assert_called_once()

    def test_stop_segment_returns_none_when_idle(self, session_state, fake_ffmpeg):
        rec = Recorder(session_state, max_segment=1800, layout="merge")
        assert rec.stop_segment() is None

    def test_segments_get_layout_and_bitrate(self, session_state, fake_ffmpeg):
        rec = Recorder(session_state, max_segment=1800, layout="merge")
        rec.start_segment()
        rec.stop_segment()
        # Trocar layout em runtime → próximo seg deve ter "split"
        rec.layout = "split"
        rec.start_segment()
        rec.stop_segment()
        layouts = [s.layout for s in rec.state.segments]
        assert layouts == ["merge", "split"]

    def test_finalize_concats_valid_segments(self, session_state, fake_ffmpeg):
        rec = Recorder(session_state, max_segment=1800, layout="merge")
        rec.start_segment()
        rec.stop_segment()
        rec.start_segment()
        rec.stop_segment()
        final = rec.finalize()
        assert final is not None
        assert final.exists()
        assert rec.state.finished is True
        assert "Test_20260101_120000.opus" in final.name

    def test_finalize_returns_none_when_no_valid_segments(self, session_state):
        rec = Recorder(session_state, max_segment=1800, layout="merge")
        # Sem segmentos
        assert rec.finalize() is None

    def test_finalize_homogeneous_uses_copy(
        self,
        session_state,
        fake_ffmpeg,
        monkeypatch,
    ):
        """Todos os segmentos com mesmo layout/bitrate → -c copy."""
        captured_cmd = []

        original_run = recorder_mod.subprocess.run

        def capture_run(cmd, **kw):
            captured_cmd.append(cmd)
            return original_run(cmd, **kw)

        monkeypatch.setattr(recorder_mod.subprocess, "run", capture_run)

        rec = Recorder(session_state, max_segment=1800, layout="merge")
        rec.start_segment()
        rec.stop_segment()
        rec.start_segment()
        rec.stop_segment()
        rec.finalize()

        # último cmd é o concat — deve ter "copy", não "libopus"
        concat_cmd = captured_cmd[-1]
        assert "-c" in concat_cmd
        assert "copy" in concat_cmd
        assert "libopus" not in concat_cmd

    def test_finalize_heterogeneous_forces_reencode(
        self,
        session_state,
        fake_ffmpeg,
        monkeypatch,
    ):
        """Layout trocou → reencode (libopus)."""
        captured_cmd = []
        original_run = recorder_mod.subprocess.run

        def capture_run(cmd, **kw):
            captured_cmd.append(cmd)
            return original_run(cmd, **kw)

        monkeypatch.setattr(recorder_mod.subprocess, "run", capture_run)

        rec = Recorder(session_state, max_segment=1800, layout="merge")
        rec.start_segment()
        rec.stop_segment()
        rec.layout = "split"
        rec.start_segment()
        rec.stop_segment()
        rec.finalize()

        concat_cmd = captured_cmd[-1]
        assert "libopus" in concat_cmd

    def test_watchdog_tick_cycles_segment(
        self,
        session_state,
        fake_ffmpeg,
        monkeypatch,
    ):
        """Quando elapsed >= max_segment, watchdog_tick rotaciona segmento."""
        rec = Recorder(session_state, max_segment=1, layout="merge")
        rec.start_segment()
        # Simula passagem do tempo
        import time

        rec.seg_start_mono = time.monotonic() - 2.0  # passou 2s, max=1
        ev = rec.watchdog_tick()
        assert ev == "cycled"
        assert rec.recording is True  # já abriu próximo
        assert len(rec.state.segments) == 1  # primeiro fechado, segundo aberto

    def test_watchdog_tick_detects_died_processes(
        self,
        session_state,
        fake_ffmpeg,
    ):
        rec = Recorder(session_state, max_segment=1800, layout="merge")
        rec.start_segment()
        # Mata os dois mocks
        rec.proc_sys._alive = False
        rec.proc_mic._alive = False
        ev = rec.watchdog_tick()
        assert ev == "died"
        assert rec.recording is False
