"""Tests for config defaults and XDG paths."""
from __future__ import annotations

import json
from pathlib import Path

from recordo import config


def test_xdg_paths_defined():
    assert config.SOCKET_PATH.name == "recordo.sock"
    assert config.AUTO_DETECT_CONFIG.name == "auto-detect.json"
    assert config.NOTAS_DIR == Path.home() / "Notas"


def test_default_auto_detect_keys():
    keys = set(config.DEFAULT_AUTO_DETECT.keys())
    assert {"enabled", "apps", "deny_apps", "min_mic_duration_seconds",
            "quiet_period_after_stop_minutes", "poll_interval_seconds"} <= keys


def test_default_auto_detect_disabled():
    assert config.DEFAULT_AUTO_DETECT["enabled"] is False


def test_load_auto_detect_creates_default(tmp_path, monkeypatch):
    cfg_path = tmp_path / "auto-detect.json"
    monkeypatch.setattr(config, "AUTO_DETECT_CONFIG", cfg_path)
    cfg = config.load_auto_detect_config()
    assert cfg["enabled"] is False
    assert cfg_path.exists()
    data = json.loads(cfg_path.read_text())
    assert "apps" in data


def test_load_auto_detect_merges_user_overrides(tmp_path, monkeypatch):
    cfg_path = tmp_path / "auto-detect.json"
    cfg_path.write_text(json.dumps({"enabled": True, "apps": ["only-app"]}))
    monkeypatch.setattr(config, "AUTO_DETECT_CONFIG", cfg_path)
    cfg = config.load_auto_detect_config()
    assert cfg["enabled"] is True
    assert cfg["apps"] == ["only-app"]
    # merged keys
    assert "deny_apps" in cfg


def test_hard_cap_seconds():
    assert config.HARD_CAP_SECONDS == 4 * 3600
