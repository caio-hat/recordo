"""Configurações, paths XDG e config.toml schema."""

from __future__ import annotations

import json
import logging
import os
import shutil
import sys
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib  # type: ignore[import-not-found]

# ── Paths XDG ───────────────────────────────────────────────────────────────
DEFAULT_OUTPUT_DIR = Path.home() / "recordings"
NOTAS_DIR = Path.home() / "Notas"

XDG_RUNTIME = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))
XDG_CONFIG = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
XDG_STATE = Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state")))
XDG_DATA = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share")))

SOCKET_PATH = XDG_RUNTIME / "recordo.sock"
LOCKFILE = Path("/tmp/recordo.lock")
NOTIF_FILE = Path("/tmp/recordo.notif_id")
DAEMON_LOG = Path("/tmp/recordo.log")
CONFIG_DIR = XDG_CONFIG / "recordo"
STATE_DIR = XDG_STATE / "recordo"
CONFIG_TOML = CONFIG_DIR / "config.toml"
LEGACY_AUTO_DETECT_JSON = CONFIG_DIR / "auto-detect.json"
SESSION_META = "session.json"

# ── Defaults ────────────────────────────────────────────────────────────────
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"
log = logging.getLogger("recordo")

DEFAULTS: dict[str, Any] = {
    "general": {
        "output_dir": str(DEFAULT_OUTPUT_DIR),
        "notas_dir": str(NOTAS_DIR),
    },
    "recording": {
        "bitrate": "32k",
        "layout": "merge",  # merge | split
        "max_segment": 1800,
        "hard_cap_seconds": 4 * 3600,
    },
    "watchdog": {
        "silence_threshold_db": -50.0,
        "silence_max_seconds": 10 * 60,
        "silence_check_interval": 30,
        "reminder_interval": 15 * 60,
    },
    "transcriber": {
        "backend": "whisper",  # whisper | parakeet
        "language": "pt",
        "whisper": {
            "model": "large-v3-turbo",
            "device": "cpu",
            "compute_type": "int8",
            "beam_size": 5,
            "vad_filter": True,
        },
        "parakeet": {
            "model": "nvidia/parakeet-tdt-0.6b-v3",
            "use_onnx": False,
        },
    },
    "auto_detect": {
        "enabled": False,
        "apps": [
            "teams-for-linux",
            "Teams",
            "Microsoft.Teams",
            "zoom",
            "Zoom",
            "Google Chrome",
            "Chromium",
            "chrome",
            "Brave",
            "firefox",
            "Firefox",
            "Mozilla Firefox",
            "Slack",
            "Discord",
            "discord",
            "WebRTC VoiceEngine",
        ],
        "deny_apps": [],
        "min_mic_duration_seconds": 8,
        "quiet_period_after_stop_minutes": 5,
        "poll_interval_seconds": 5,
    },
    "ui": {
        "theme": "auto",  # auto | light | dark
        "window_remember": True,
        "last_window_geometry": "",
    },
}


# ── TOML writer (sem dep externa) ───────────────────────────────────────────
def _toml_dump(data: dict[str, Any], indent: int = 0) -> str:
    """Serializador TOML simples e suficiente pro nosso schema."""
    lines: list[str] = []
    return _toml_section(data, [], lines)


def _toml_section(data: dict[str, Any], path: list[str], lines: list[str]) -> str:
    inline_keys: list[tuple[str, Any]] = []
    nested: list[tuple[str, dict[str, Any]]] = []
    for k, v in data.items():
        if isinstance(v, dict):
            nested.append((k, v))
        else:
            inline_keys.append((k, v))

    if path:
        if lines and lines[-1] != "":
            lines.append("")
        lines.append(f"[{'.'.join(path)}]")

    for k, v in inline_keys:
        lines.append(f"{k} = {_toml_value(v)}")

    for k, v in nested:
        _toml_section(v, [*path, k], lines)

    return "\n".join(lines) + "\n"


def _toml_value(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, str):
        return _toml_str(v)
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, list):
        if not v:
            return "[]"
        return "[" + ", ".join(_toml_value(x) for x in v) + "]"
    raise TypeError(f"unsupported TOML value type: {type(v)}")


def _toml_str(s: str) -> str:
    escaped = s.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


# ── deep merge ──────────────────────────────────────────────────────────────
def _deep_merge(base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    """Merge recursivo: overrides ganha. Listas substituem (não concatenam)."""
    result = deepcopy(base)
    for k, v in overrides.items():
        if isinstance(v, dict) and isinstance(result.get(k), dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


# ── Migração JSON legacy ────────────────────────────────────────────────────
def _migrate_legacy_json(overrides: dict[str, Any]) -> dict[str, Any]:
    """Se auto-detect.json existe, popula [auto_detect] no TOML novo."""
    if not LEGACY_AUTO_DETECT_JSON.exists():
        return overrides
    try:
        legacy = json.loads(LEGACY_AUTO_DETECT_JSON.read_text())
        overrides.setdefault("auto_detect", {})
        for k, v in legacy.items():
            overrides["auto_detect"].setdefault(k, v)
        backup = LEGACY_AUTO_DETECT_JSON.with_suffix(".json.bak")
        shutil.move(str(LEGACY_AUTO_DETECT_JSON), backup)
        log.info("migrou auto-detect.json legacy → config.toml (backup: %s)", backup)
    except Exception as e:
        log.warning("falha migrando auto-detect.json: %s", e)
    return overrides


# ── Load / Save ─────────────────────────────────────────────────────────────
def load_config() -> dict[str, Any]:
    """Carrega config.toml + merge com defaults. Cria default se ausente."""
    if not CONFIG_TOML.exists():
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        overrides = _migrate_legacy_json({})
        merged = _deep_merge(DEFAULTS, overrides)
        save_config(merged)
        return merged

    try:
        with CONFIG_TOML.open("rb") as f:
            overrides = tomllib.load(f)
    except Exception as e:
        log.error("config.toml inválido (%s) — usando defaults", e)
        return deepcopy(DEFAULTS)

    overrides = _migrate_legacy_json(overrides)
    return _deep_merge(DEFAULTS, overrides)


def save_config(cfg: dict[str, Any]) -> None:
    """Salva config atômico (tempfile + os.replace)."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    header = (
        "# Recordo — config.toml\n"
        "# Documentação: https://github.com/caio-hat/recordo/blob/main/docs/configuration.md\n"
        "# Recarrega via: recordo --reload-config (sem restart do daemon)\n\n"
    )
    body = _toml_dump(cfg)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=CONFIG_DIR,
        delete=False,
        prefix=".config-",
        suffix=".toml.tmp",
    ) as tmp:
        tmp.write(header)
        tmp.write(body)
        tmp_path = Path(tmp.name)
    os.replace(tmp_path, CONFIG_TOML)


# ── Backward-compat constantes (statics, defaults; runtime usa load_config) ─
HARD_CAP_SECONDS: int = DEFAULTS["recording"]["hard_cap_seconds"]
REMINDER_INTERVAL: int = DEFAULTS["watchdog"]["reminder_interval"]
SILENCE_THRESHOLD_DB: float = DEFAULTS["watchdog"]["silence_threshold_db"]
SILENCE_MAX_SECONDS: int = DEFAULTS["watchdog"]["silence_max_seconds"]
SILENCE_CHECK_INTERVAL: int = DEFAULTS["watchdog"]["silence_check_interval"]
DEFAULT_MAX_SEGMENT: int = DEFAULTS["recording"]["max_segment"]
DEFAULT_AUTO_DETECT: dict = DEFAULTS["auto_detect"]


def load_auto_detect_config() -> dict:
    """[deprecated] Use load_config()['auto_detect']."""
    return load_config().get("auto_detect", DEFAULTS["auto_detect"])


def setup_logging(verbose: bool = False) -> None:
    """Configura logging pra console + file."""
    level = logging.DEBUG if verbose else logging.INFO
    handlers: list[logging.Handler] = [logging.FileHandler(str(DAEMON_LOG))]
    if verbose:
        handlers.append(logging.StreamHandler())
    logging.basicConfig(level=level, format=LOG_FORMAT, handlers=handlers, force=True)
