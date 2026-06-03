"""Testes para tray state queries (sem GUI)."""

from __future__ import annotations

from unittest.mock import patch


def test_query_state_when_daemon_dead():
    from recordo import tray

    with patch("recordo.tray.is_daemon_alive", return_value=False):
        state = tray._query_state()
        assert state["alive"] is False
        assert state["recording"] is False
        assert state["last_recordings"] == []


def test_query_state_when_daemon_alive_not_recording():
    from recordo import tray

    fake_resp = {"ok": True, "recording": False, "subject": None, "duration_s": 0}
    with (
        patch("recordo.tray.is_daemon_alive", return_value=True),
        patch("recordo.tray.send_to_daemon", return_value=fake_resp),
    ):
        state = tray._query_state()
        assert state["alive"] is True
        assert state["recording"] is False
        assert state["duration_s"] == 0


def test_query_state_when_daemon_alive_recording():
    from recordo import tray

    fake_resp = {"ok": True, "recording": True, "subject": "Daily", "elapsed_seconds": 120}
    with (
        patch("recordo.tray.is_daemon_alive", return_value=True),
        patch("recordo.tray.send_to_daemon", return_value=fake_resp),
    ):
        state = tray._query_state()
        assert state["alive"] is True
        assert state["recording"] is True
        assert state["subject"] == "Daily"
        assert state["duration_s"] == 120
