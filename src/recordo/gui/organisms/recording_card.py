# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Caio Hat
"""RecordingCard — representação de uma gravação com resumo + botão ver detalhes."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk

from ..atoms import ActionButton, Caption, Heading, StatusBadge
from ..molecules import Card


def _read_duration(rec_dir: Path) -> str:
    nota = rec_dir / "nota.md"
    if not nota.exists():
        return ""
    try:
        for line in nota.read_text(encoding="utf-8").splitlines()[:15]:
            if line.startswith("duration_min:"):
                val = float(line.split(":", 1)[1].strip())
                return f"{int(val * 60)}s" if val < 1 else f"{val:.1f} min"
    except Exception:
        pass
    return ""


def _badges_for(rec_dir: Path) -> list[tuple[str, str]]:
    """Retorna lista [(variant, label)] indicando o que existe."""
    badges: list[tuple[str, str]] = []
    if (rec_dir / "transcricao.txt").exists():
        badges.append(("success", "✍ Transcrito"))
    if (rec_dir / "summary.md").exists():
        badges.append(("info", "📝 Resumido"))
    if (rec_dir / "tasks.md").exists():
        badges.append(("info", "✅ Tarefas"))
    return badges


class RecordingCard(Card):
    """Card de uma gravação com título, badges e botão ver detalhes."""

    def __init__(
        self,
        rec_dir: Path,
        *,
        on_view: Callable[[Path], None] | None = None,
        on_open_folder: Callable[[Path], None] | None = None,
    ):
        super().__init__(variant="interactive", spacing=8)
        self._dir = rec_dir

        # Header: título + duração + badges
        title = Heading(rec_dir.name.replace("_", " "), level=3)
        self.append(title)

        meta_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        dur = _read_duration(rec_dir)
        if dur:
            meta_box.append(Caption(f"⏱ {dur}"))
        for variant, label in _badges_for(rec_dir):
            meta_box.append(StatusBadge(variant, label))
        self.append(meta_box)

        # Ações
        action_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8, halign=Gtk.Align.END)
        if on_view:
            btn_view = ActionButton("Ver detalhes", variant="primary", on_click=lambda: on_view(rec_dir))
            action_box.append(btn_view)
        if on_open_folder:
            btn_open = ActionButton("Abrir pasta", variant="flat", on_click=lambda: on_open_folder(rec_dir))
            action_box.append(btn_open)
        self.append(action_box)
