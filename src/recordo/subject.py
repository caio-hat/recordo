"""Detecção do assunto da gravação via título da janela ativa."""
from __future__ import annotations

import re
import subprocess
from datetime import datetime

# Heurísticas — primeira que casa ganha
_PATTERNS: list[tuple[str, str]] = [
    (r"^(.+?) \| Microsoft Teams\b", "Teams"),
    (r"^(.+?) - Microsoft Teams\b", "Teams"),
    (r"^Reunião em\s+(.+?)(?:\s+\|.*)?$", "Teams"),
    (r"^Meeting in\s+(.+?)(?:\s+\|.*)?$", "Teams"),
    (r"^(.+?) - Google Meet", "Meet"),
    (r"^Meet\s+-\s+(.+)", "Meet"),
    (r"^(.+?) Zoom Meeting", "Zoom"),
    (r"^Zoom\s+Meeting\s*-\s*(.+)", "Zoom"),
    (r"^Huddle in\s+(.+)", "Slack"),
    (r"^(.+?)\s+- Slack", "Slack"),
    (r"^(.+?)\s+- Discord", "Discord"),
]


def _active_window_title() -> str:
    """Pega título da janela ativa via xdotool (X11). Retorna '' se falhar."""
    try:
        out = subprocess.check_output(
            ["xdotool", "getactivewindow", "getwindowname"],
            text=True, stderr=subprocess.DEVNULL, timeout=2,
        )
        return out.strip()
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return ""


def safe_subject(text: str) -> str:
    """Sanitiza string pra uso em nome de pasta/arquivo."""
    cleaned = re.sub(r"[^A-Za-z0-9 _\-À-ÿ]+", "", text).strip()
    cleaned = re.sub(r"\s+", "_", cleaned)
    return cleaned[:80] or "Gravacao"


def detect_subject_from_title(title: str) -> str:
    """Extrai subject de um título de janela conhecido (puro — testável)."""
    for pat, _app in _PATTERNS:
        if m := re.match(pat, title):
            return safe_subject(m.group(1).strip())
    return f"call_{datetime.now():%Y-%m-%d_%Hh%M}"


def detect_subject() -> str:
    """Pega título da janela ativa e aplica heurísticas, fallback timestamp."""
    title = _active_window_title()
    if not title:
        return f"call_{datetime.now():%Y-%m-%d_%Hh%M}"
    return detect_subject_from_title(title)
