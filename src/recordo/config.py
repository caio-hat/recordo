"""Configurações, paths XDG e defaults."""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

# ── Paths XDG ───────────────────────────────────────────────────────────────
DEFAULT_OUTPUT_DIR = Path.home() / "recordings"
NOTAS_DIR = Path.home() / "Notas"

XDG_RUNTIME = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))
XDG_CONFIG = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
XDG_STATE = Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state")))
XDG_DATA = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share")))

SOCKET_PATH = XDG_RUNTIME / "recordo.sock"
LOCKFILE = Path("/tmp/recordo.lock")  # nosec: lockfile not sensitive
NOTIF_FILE = Path("/tmp/recordo.notif_id")  # nosec
DAEMON_LOG = Path("/tmp/recordo.log")  # nosec
CONFIG_DIR = XDG_CONFIG / "recordo"
STATE_DIR = XDG_STATE / "recordo"
AUTO_DETECT_CONFIG = CONFIG_DIR / "auto-detect.json"
SESSION_META = "session.json"

# ── Limites e thresholds ────────────────────────────────────────────────────
HARD_CAP_SECONDS = 4 * 3600  # cap absoluto (proteção catastrófica)
REMINDER_INTERVAL = 15 * 60  # notify "ainda gravando" a cada 15min
SILENCE_THRESHOLD_DB = -50.0
SILENCE_MAX_SECONDS = 10 * 60  # auto-stop por silêncio mic
SILENCE_CHECK_INTERVAL = 30
DEFAULT_MAX_SEGMENT = 1800  # 30min por segmento, auto-cycle

# ── Auto-detect defaults ────────────────────────────────────────────────────
DEFAULT_AUTO_DETECT = {
    "enabled": False,
    "apps": [
        "teams-for-linux", "Teams", "Microsoft.Teams",
        "zoom", "Zoom",
        "Google Chrome", "Chromium", "chrome", "Brave",
        "firefox", "Firefox", "Mozilla Firefox",
        "Slack", "Discord", "discord",
        "WebRTC VoiceEngine",
    ],
    "deny_apps": [],
    "min_mic_duration_seconds": 8,
    "quiet_period_after_stop_minutes": 5,
    "poll_interval_seconds": 5,
}

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"
log = logging.getLogger("recordo")


def load_auto_detect_config() -> dict:
    """Carrega config auto-detect, criando default se ausente."""
    if not AUTO_DETECT_CONFIG.exists():
        AUTO_DETECT_CONFIG.parent.mkdir(parents=True, exist_ok=True)
        AUTO_DETECT_CONFIG.write_text(json.dumps(DEFAULT_AUTO_DETECT, indent=2))
        return dict(DEFAULT_AUTO_DETECT)
    try:
        return {**DEFAULT_AUTO_DETECT, **json.loads(AUTO_DETECT_CONFIG.read_text())}
    except Exception as e:
        log.error("auto-detect config inválida (%s) — usando default", e)
        return dict(DEFAULT_AUTO_DETECT)


def setup_logging(verbose: bool = False) -> None:
    """Configura logging pra console + file."""
    level = logging.DEBUG if verbose else logging.INFO
    handlers: list[logging.Handler] = [logging.FileHandler(str(DAEMON_LOG))]
    if verbose:
        handlers.append(logging.StreamHandler())
    logging.basicConfig(level=level, format=LOG_FORMAT, handlers=handlers, force=True)
