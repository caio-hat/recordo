"""Testes do Daemon: lifecycle do socket + comandos JSON-line.

Estratégia: subimos o daemon em um event loop, mockamos as primitivas que
tocam ffmpeg e PulseAudio (list_sources, auto_pick, Recorder.*), e exercemos
os comandos via cliente UNIX socket real.
"""

from __future__ import annotations

import asyncio
import json
import socket
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from recordo import daemon as daemon_mod
from recordo.daemon import Daemon


@pytest.fixture
def fake_socket(tmp_path, monkeypatch):
    """Redireciona SOCKET_PATH e CONFIG_TOML pra dentro do tmp."""
    sock_path = tmp_path / "recordo.sock"
    monkeypatch.setattr(daemon_mod, "SOCKET_PATH", sock_path)
    return sock_path


@pytest.fixture
def fake_recorder(monkeypatch):
    """Mocka Recorder e affins pra evitar ffmpeg real."""
    rec_instance = MagicMock()
    rec_instance.recording = False
    rec_instance.start_segment = MagicMock(
        side_effect=lambda: setattr(rec_instance, "recording", True),
    )
    rec_instance.stop_segment = MagicMock()
    rec_instance.finalize = MagicMock(return_value=None)

    def make_rec(state, **kw):
        return rec_instance

    monkeypatch.setattr(daemon_mod, "Recorder", make_rec)
    monkeypatch.setattr(daemon_mod, "set_recorder_ref", lambda r: None)
    monkeypatch.setattr(daemon_mod, "write_report", lambda *a, **kw: None)

    # Mocka detect_subject pra retornar valor previsível
    monkeypatch.setattr(daemon_mod, "detect_subject", lambda: "Reunião Teste")

    # Mocka list_sources e auto_pick
    monkeypatch.setattr(daemon_mod, "list_sources", lambda: ["mock_source"])
    monkeypatch.setattr(
        daemon_mod,
        "auto_pick",
        lambda sources: ("alsa_input.test", "alsa_output.test.monitor"),
    )

    # Mocka make_session: cria uma SessionState mínima
    def fake_make_session(subject, mic, sys_, **kw):
        from recordo.recorder import SessionState

        out = Path(kw.get("base_dir", "/tmp")) / f"{subject}_test"
        out.mkdir(parents=True, exist_ok=True)
        return SessionState(
            subject=subject,
            session_id="testid",
            started_at="2026-01-01T12:00:00",
            output_dir=str(out),
            mic_source=mic,
            sys_source=sys_,
            codec="opus",
            bitrate=kw.get("bitrate", "32k"),
            layout=kw.get("layout", "merge"),
        )

    monkeypatch.setattr(daemon_mod, "make_session", fake_make_session)
    return rec_instance


@pytest.fixture
def fake_notify(monkeypatch):
    monkeypatch.setattr(daemon_mod, "notify", lambda *a, **kw: None)


async def _start_daemon_in_task(daemon: Daemon) -> asyncio.Task:
    task = asyncio.create_task(daemon.run())
    # Aguarda socket aparecer
    for _ in range(50):
        if Path(daemon_mod.SOCKET_PATH).exists():
            return task
        await asyncio.sleep(0.05)
    raise TimeoutError("daemon não criou socket")


async def _send_cmd(cmd: str, **kwargs) -> dict:
    """Cliente síncrono em executor → não bloqueia loop."""
    loop = asyncio.get_event_loop()

    def _client():
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(3)
        s.connect(str(daemon_mod.SOCKET_PATH))
        payload = json.dumps({"cmd": cmd, **kwargs}) + "\n"
        s.sendall(payload.encode("utf-8"))
        data = b""
        while not data.endswith(b"\n"):
            chunk = s.recv(4096)
            if not chunk:
                break
            data += chunk
        s.close()
        return json.loads(data.decode("utf-8"))

    return await loop.run_in_executor(None, _client)


async def _stop_daemon(task: asyncio.Task) -> None:
    """Manda quit + aguarda."""
    try:
        await _send_cmd("quit")
    except Exception:
        pass
    try:
        await asyncio.wait_for(task, timeout=3)
    except (TimeoutError, asyncio.CancelledError):
        task.cancel()


@pytest.mark.asyncio
async def test_status_on_idle_daemon(fake_socket, fake_recorder, fake_notify, tmp_path):
    d = Daemon(
        output_dir=tmp_path,
        config={
            "general": {"output_dir": str(tmp_path), "notas_dir": str(tmp_path)},
            "recording": {
                "bitrate": "32k",
                "layout": "merge",
                "max_segment": 1800,
                "hard_cap_seconds": 14400,
            },
            "watchdog": {
                "silence_threshold_db": -50,
                "silence_max_seconds": 600,
                "silence_check_interval": 30,
                "reminder_interval": 900,
            },
            "transcriber": {
                "backend": "whisper",
                "language": "pt",
                "whisper": {"model": "x"},
                "parakeet": {"model": "y"},
            },
            "auto_detect": {
                "enabled": False,
                "apps": [],
                "deny_apps": [],
                "min_mic_duration_seconds": 8,
                "quiet_period_after_stop_minutes": 5,
                "poll_interval_seconds": 5,
            },
            "ui": {"theme": "auto", "window_remember": True, "last_window_geometry": ""},
        },
    )
    task = await _start_daemon_in_task(d)
    try:
        resp = await _send_cmd("status")
        assert resp["ok"] is True
        assert resp["recording"] is False
    finally:
        await _stop_daemon(task)


@pytest.mark.asyncio
async def test_unknown_command_returns_error(fake_socket, fake_recorder, fake_notify, tmp_path):
    d = Daemon(
        output_dir=tmp_path,
        config={
            "general": {"output_dir": str(tmp_path), "notas_dir": str(tmp_path)},
            "recording": {
                "bitrate": "32k",
                "layout": "merge",
                "max_segment": 1800,
                "hard_cap_seconds": 14400,
            },
            "watchdog": {
                "silence_threshold_db": -50,
                "silence_max_seconds": 600,
                "silence_check_interval": 30,
                "reminder_interval": 900,
            },
            "transcriber": {
                "backend": "whisper",
                "language": "pt",
                "whisper": {"model": "x"},
                "parakeet": {"model": "y"},
            },
            "auto_detect": {
                "enabled": False,
                "apps": [],
                "deny_apps": [],
                "min_mic_duration_seconds": 8,
                "quiet_period_after_stop_minutes": 5,
                "poll_interval_seconds": 5,
            },
            "ui": {"theme": "auto", "window_remember": True, "last_window_geometry": ""},
        },
    )
    task = await _start_daemon_in_task(d)
    try:
        resp = await _send_cmd("nonsense")
        assert resp["ok"] is False
        assert "desconhecido" in resp["error"].lower()
    finally:
        await _stop_daemon(task)


@pytest.mark.asyncio
async def test_invalid_json_returns_error(fake_socket, fake_recorder, fake_notify, tmp_path):
    d = Daemon(
        output_dir=tmp_path,
        config={
            "general": {"output_dir": str(tmp_path), "notas_dir": str(tmp_path)},
            "recording": {
                "bitrate": "32k",
                "layout": "merge",
                "max_segment": 1800,
                "hard_cap_seconds": 14400,
            },
            "watchdog": {
                "silence_threshold_db": -50,
                "silence_max_seconds": 600,
                "silence_check_interval": 30,
                "reminder_interval": 900,
            },
            "transcriber": {
                "backend": "whisper",
                "language": "pt",
                "whisper": {"model": "x"},
                "parakeet": {"model": "y"},
            },
            "auto_detect": {
                "enabled": False,
                "apps": [],
                "deny_apps": [],
                "min_mic_duration_seconds": 8,
                "quiet_period_after_stop_minutes": 5,
                "poll_interval_seconds": 5,
            },
            "ui": {"theme": "auto", "window_remember": True, "last_window_geometry": ""},
        },
    )
    task = await _start_daemon_in_task(d)
    try:
        loop = asyncio.get_event_loop()

        def raw_send():
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.settimeout(3)
            s.connect(str(daemon_mod.SOCKET_PATH))
            s.sendall(b"not-json\n")
            data = s.recv(4096)
            s.close()
            return json.loads(data.decode("utf-8"))

        resp = await loop.run_in_executor(None, raw_send)
        assert resp["ok"] is False
        assert "JSON" in resp["error"] or "json" in resp["error"]
    finally:
        await _stop_daemon(task)
