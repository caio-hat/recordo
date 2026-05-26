"""Detecção do assunto da gravação via título da janela ativa.

Suporta X11 (xdotool, wmctrl) e Wayland (swaymsg, hyprctl). Em Wayland sem
compositor compatível, loga warning e cai pro fallback timestamp — preferível
a falhar silenciosamente.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
from datetime import datetime

log = logging.getLogger(__name__)

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


def _is_wayland() -> bool:
    """Heurística simples: WAYLAND_DISPLAY ou XDG_SESSION_TYPE=wayland."""
    return (
        os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland"
        or bool(os.environ.get("WAYLAND_DISPLAY"))
    )


def _try_x11_xdotool() -> str:
    """X11 via xdotool (default)."""
    if not shutil.which("xdotool"):
        return ""
    try:
        out = subprocess.check_output(
            ["xdotool", "getactivewindow", "getwindowname"],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=2,
        )
        return out.strip()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return ""


def _try_x11_wmctrl() -> str:
    """X11 via wmctrl (fallback se xdotool falhar)."""
    if not shutil.which("wmctrl"):
        return ""
    try:
        out = subprocess.check_output(
            ["wmctrl", "-a", ":ACTIVE:", "-v"],
            text=True, stderr=subprocess.PIPE, timeout=2,
        )
        # output formato: "Using window: 0xNNN" — não é título
        # melhor: 'wmctrl -lp' + parse pelo PID ativo. Mais frágil. Skip.
        return out.strip()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return ""


def _try_wayland_sway() -> str:
    """Wayland Sway/i3 via swaymsg/i3-msg."""
    for cmd in (["swaymsg", "-t", "get_tree"], ["i3-msg", "-t", "get_tree"]):
        if not shutil.which(cmd[0]):
            continue
        try:
            out = subprocess.check_output(cmd, text=True, timeout=2)
            tree = json.loads(out)
            return _find_focused_title(tree) or ""
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
                json.JSONDecodeError):
            continue
    return ""


def _find_focused_title(node: dict) -> str | None:
    """Walk recursivo numa tree i3/sway pra achar window focada."""
    if node.get("focused") and node.get("name"):
        return node["name"]
    for key in ("nodes", "floating_nodes"):
        for child in node.get(key, []):
            t = _find_focused_title(child)
            if t:
                return t
    return None


def _try_wayland_hyprland() -> str:
    """Hyprland via hyprctl."""
    if not shutil.which("hyprctl"):
        return ""
    try:
        out = subprocess.check_output(
            ["hyprctl", "activewindow", "-j"], text=True, timeout=2,
        )
        data = json.loads(out)
        return data.get("title", "") or ""
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
            json.JSONDecodeError):
        return ""


def _active_window_title() -> str:
    """Pega título da janela ativa. Tenta X11 e Wayland.

    Ordem:
      1. xdotool (X11, mais comum)
      2. swaymsg/i3-msg (Wayland Sway/i3)
      3. hyprctl (Hyprland)

    Retorna '' se nenhum funcionar (fallback fica com o caller).
    """
    # X11 sempre primeiro — Cinnamon/Mint/Ubuntu default ainda é X11
    if t := _try_x11_xdotool():
        return t

    if _is_wayland():
        for fn in (_try_wayland_sway, _try_wayland_hyprland):
            if t := fn():
                return t
        log.warning(
            "Wayland sem compositor suportado para captura de janela ativa. "
            "Usando fallback timestamp. Suporte: sway, i3, hyprland."
        )
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
