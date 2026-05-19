"""Wrapper notify-send com replace-id (padrão mute.sh do user)."""

from __future__ import annotations

import logging
import subprocess

from .config import NOTIF_FILE

log = logging.getLogger(__name__)


def notify(
    title: str,
    body: str = "",
    *,
    urgency: str = "normal",
    icon: str = "media-record",
    replace: bool = True,
    transient: bool = False,
) -> None:
    """Envia notificação desktop. Reusa ID anterior pra evitar empilhar."""
    cmd = ["notify-send", "-u", urgency, "-a", "Recordo", "-i", icon, "-p"]
    if transient:
        cmd += ["-h", "int:transient:1"]
    if replace and NOTIF_FILE.exists():
        try:
            cmd += ["-r", NOTIF_FILE.read_text().strip()]
        except Exception:
            pass
    cmd += [title, body]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=3)
        if result.returncode == 0 and result.stdout.strip().isdigit():
            NOTIF_FILE.write_text(result.stdout.strip())
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        log.warning("notify-send falhou: %s", e)
