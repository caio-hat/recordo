"""RecordingRow — Adw.ActionRow listando uma gravação em ~/Notas."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from gi.repository import Adw, Gtk


class RecordingRow(Adw.ActionRow):
    def __init__(self, dir_: Path):
        super().__init__()
        self.dir = dir_
        self._open_cb = None

        # Parse data + subject do nome do diretório
        name = dir_.name
        m = re.match(r"^(\d{4}-\d{2}-\d{2})_(.+)$", name)
        if m:
            date_str, subject = m.groups()
            subject = subject.replace("_", " ")
            self.set_title(subject)
            try:
                dt = datetime.strptime(date_str, "%Y-%m-%d")
                pretty = dt.strftime("%d %b %Y")
            except ValueError:
                pretty = date_str
            self.set_subtitle(pretty)
        else:
            self.set_title(name)

        # Duration via nota.md frontmatter
        duration = self._read_duration()
        if duration:
            label = Gtk.Label(label=duration)
            label.add_css_class("dim-label")
            self.add_suffix(label)

        # Botão abrir
        btn = Gtk.Button(icon_name="document-open-symbolic")
        btn.add_css_class("flat")
        btn.set_valign(Gtk.Align.CENTER)
        btn.connect("clicked", self._on_open)
        self.add_suffix(btn)

    def _read_duration(self) -> str:
        nota = self.dir / "nota.md"
        if not nota.exists():
            return ""
        try:
            for line in nota.read_text(encoding="utf-8").splitlines()[:15]:
                if line.startswith("duration_min:"):
                    val = float(line.split(":", 1)[1].strip())
                    if val < 1:
                        return f"{int(val * 60)}s"
                    return f"{val:.1f} min"
        except Exception:
            pass
        return ""

    def connect_open(self, cb) -> None:
        self._open_cb = cb

    def _on_open(self, _btn) -> None:
        if self._open_cb:
            self._open_cb(self.dir)
