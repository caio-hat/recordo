"""Tests for config defaults, XDG paths, and TOML round-trip."""

from __future__ import annotations

import json
from pathlib import Path

from recordo import config


def test_xdg_paths_defined():
    assert config.SOCKET_PATH.name == "recordo.sock"
    assert config.CONFIG_TOML.name == "config.toml"
    assert config.NOTAS_DIR == Path.home() / "Notas"


def test_default_auto_detect_keys():
    keys = set(config.DEFAULT_AUTO_DETECT.keys())
    assert {
        "enabled",
        "apps",
        "deny_apps",
        "min_mic_duration_seconds",
        "quiet_period_after_stop_minutes",
        "poll_interval_seconds",
    } <= keys


def test_default_auto_detect_disabled():
    assert config.DEFAULT_AUTO_DETECT["enabled"] is False


def test_load_config_creates_default(tmp_path, monkeypatch):
    """Sem config.toml: cria com defaults."""
    cfg_path = tmp_path / "config.toml"
    monkeypatch.setattr(config, "CONFIG_TOML", cfg_path)
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(
        config, "LEGACY_AUTO_DETECT_JSON", tmp_path / "auto-detect.json"
    )

    cfg = config.load_config()
    assert cfg["recording"]["bitrate"] == "32k"
    assert cfg["auto_detect"]["enabled"] is False
    assert cfg_path.exists()
    # round-trip: arquivo gerado deve ser parseável de volta
    cfg2 = config.load_config()
    assert cfg2["recording"]["bitrate"] == cfg["recording"]["bitrate"]


def test_load_config_merges_user_overrides(tmp_path, monkeypatch):
    """Overrides parciais preservam defaults nas chaves não tocadas."""
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        '[recording]\n'
        'bitrate = "48k"\n'
        '\n'
        '[auto_detect]\n'
        'enabled = true\n'
        'apps = ["only-app"]\n'
    )
    monkeypatch.setattr(config, "CONFIG_TOML", cfg_path)
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(
        config, "LEGACY_AUTO_DETECT_JSON", tmp_path / "auto-detect.json"
    )

    cfg = config.load_config()
    assert cfg["recording"]["bitrate"] == "48k"
    # default preservado:
    assert cfg["recording"]["layout"] == "merge"
    assert cfg["auto_detect"]["enabled"] is True
    assert cfg["auto_detect"]["apps"] == ["only-app"]
    # default merged:
    assert "deny_apps" in cfg["auto_detect"]


def test_legacy_json_migration(tmp_path, monkeypatch):
    """auto-detect.json legacy é migrado pra TOML e renomeado .bak."""
    legacy = tmp_path / "auto-detect.json"
    legacy.write_text(json.dumps({"enabled": True, "apps": ["zoom"]}))
    cfg_path = tmp_path / "config.toml"
    monkeypatch.setattr(config, "CONFIG_TOML", cfg_path)
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config, "LEGACY_AUTO_DETECT_JSON", legacy)

    cfg = config.load_config()
    assert cfg["auto_detect"]["enabled"] is True
    assert cfg["auto_detect"]["apps"] == ["zoom"]
    # legacy file foi renomeado:
    assert not legacy.exists()
    assert (tmp_path / "auto-detect.json.bak").exists()


def test_hard_cap_seconds():
    assert config.HARD_CAP_SECONDS == 4 * 3600


def test_load_auto_detect_config_proxies_to_load_config(tmp_path, monkeypatch):
    """API legacy load_auto_detect_config ainda funciona (deprecated)."""
    cfg_path = tmp_path / "config.toml"
    monkeypatch.setattr(config, "CONFIG_TOML", cfg_path)
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(
        config, "LEGACY_AUTO_DETECT_JSON", tmp_path / "auto-detect.json"
    )

    ad = config.load_auto_detect_config()
    assert "enabled" in ad
    assert ad["enabled"] is False
