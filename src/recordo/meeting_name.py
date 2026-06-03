# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Caio Hat
"""Auto-extract meeting name from window titles (Teams, Zoom, Meet, etc).

Estratégias em cascata:
  1. wmctrl -l: parse títulos com regex por app
  2. xdotool getactivewindow + getwindowname (X11 fallback)
  3. Retorna None se nada matcher — caller usa nome genérico
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
import unicodedata
from dataclasses import dataclass

log = logging.getLogger(__name__)

# Regex patterns por aplicação
# Ordem importa: matches mais específicos primeiro
MEETING_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    # Microsoft Teams
    ("teams", re.compile(r"^(.+?) \| Microsoft Teams$", re.IGNORECASE)),
    ("teams", re.compile(r"^Microsoft Teams - (.+?)$", re.IGNORECASE)),
    # Zoom
    ("zoom", re.compile(r"^(.+?)'s Personal Meeting Room - Zoom$", re.IGNORECASE)),
    ("zoom", re.compile(r"^Zoom - (.+?)$", re.IGNORECASE)),
    ("zoom", re.compile(r"^Zoom Meeting$", re.IGNORECASE)),
    # Google Meet (browser title)
    ("meet", re.compile(r"^Meet — (.+?)$", re.IGNORECASE)),
    ("meet", re.compile(r"^(.+?) - Google Meet$", re.IGNORECASE)),
    # Webex
    ("webex", re.compile(r"^(.+?) - Webex$", re.IGNORECASE)),
    ("webex", re.compile(r"^Webex Meetings$", re.IGNORECASE)),
    # Discord
    ("discord", re.compile(r"^(.+?) \| (.+?) \| Discord$", re.IGNORECASE)),
    ("discord", re.compile(r"^Discord$", re.IGNORECASE)),
    # Slack huddles
    ("slack", re.compile(r"^Huddle in #(.+?) \| Slack$", re.IGNORECASE)),
    ("slack", re.compile(r"^(.+?) \| Slack$", re.IGNORECASE)),
    # Skype
    ("skype", re.compile(r"^(.+?) - Skype$", re.IGNORECASE)),
    # Jitsi Meet
    ("jitsi", re.compile(r"^(.+?) - Jitsi Meet$", re.IGNORECASE)),
]


@dataclass(frozen=True)
class MeetingTitle:
    """Resultado do match de título de janela."""

    app: str  # app reconhecido (teams, zoom, meet, etc) ou 'unknown'
    raw: str  # título bruto da janela
    extracted: str | None  # parte útil extraída (None se não reconhecido)


def _list_windows_via_wmctrl() -> list[str]:
    """Retorna lista de títulos via wmctrl -l. Vazio se wmctrl ausente."""
    if not shutil.which("wmctrl"):
        return []
    try:
        r = subprocess.run(
            ["wmctrl", "-l"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=3,
        )
        if r.returncode != 0:
            return []
        titles = []
        for line in r.stdout.splitlines():
            parts = line.split(None, 3)
            if len(parts) >= 4:
                titles.append(parts[3].strip())
        return titles
    except (subprocess.SubprocessError, OSError):
        return []


def _list_windows_via_xdotool() -> list[str]:
    """Fallback X11 via xdotool. Retorna [] se ausente."""
    if not shutil.which("xdotool"):
        return []
    try:
        r = subprocess.run(
            ["xdotool", "search", "--onlyvisible", "--name", ".*"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=3,
        )
        if r.returncode != 0:
            return []
        win_ids = [w for w in r.stdout.split() if w]
        titles = []
        for wid in win_ids[:50]:
            try:
                r2 = subprocess.run(
                    ["xdotool", "getwindowname", wid],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=2,
                )
                if r2.returncode == 0:
                    titles.append(r2.stdout.strip())
            except (subprocess.SubprocessError, OSError):
                continue
        return titles
    except (subprocess.SubprocessError, OSError):
        return []


def list_window_titles() -> list[str]:
    """Retorna lista de títulos. Usa wmctrl primeiro, xdotool fallback."""
    titles = _list_windows_via_wmctrl()
    if not titles:
        titles = _list_windows_via_xdotool()
    return titles


def _match_title(title: str) -> MeetingTitle:
    """Tenta dar match no título contra os patterns conhecidos."""
    for app, pat in MEETING_PATTERNS:
        m = pat.match(title)
        if m:
            extracted = m.group(1) if m.groups() else None
            return MeetingTitle(app=app, raw=title, extracted=extracted)
    return MeetingTitle(app="unknown", raw=title, extracted=None)


def sanitize_filename(text: str, *, max_len: int = 60) -> str:
    """Sanitiza nome para uso em filesystem."""
    s = text.strip().lower()
    # Remove diacríticos (ã→a, é→e, etc)
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = re.sub(r"['\"\u201c\u201d\u2018\u2019]", "", s)
    s = re.sub(r"[^a-z0-9\s\-_]+", "", s, flags=re.UNICODE)
    s = re.sub(r"\s+", "_", s)
    s = re.sub(r"_+", "_", s)
    s = s.strip("_-")
    if len(s) > max_len:
        s = s[:max_len].rstrip("_-")
    return s


def extract_meeting_name(
    detected_app: str | None = None,
    titles: list[str] | None = None,
) -> str | None:
    """Tenta extrair nome de reunião a partir das janelas abertas.

    Args:
        detected_app: nome do app detectado pelo PulseAudio (teams, zoom, etc).
        titles: lista de títulos para testar (usa list_window_titles() se None).

    Returns:
        Nome sanitizado ou None se nenhum match.
    """
    if titles is None:
        titles = list_window_titles()
    if not titles:
        return None

    matches: list[MeetingTitle] = []
    for t in titles:
        m = _match_title(t)
        if m.extracted:
            matches.append(m)

    if not matches:
        return None

    # Se detected_app fornecido, prefere match daquele app
    if detected_app:
        app_l = detected_app.lower()
        for m in matches:
            if app_l in m.app or m.app in app_l:
                return sanitize_filename(m.extracted)  # type: ignore[arg-type]

    # Senão usa o primeiro match válido
    return sanitize_filename(matches[0].extracted)  # type: ignore[arg-type]
