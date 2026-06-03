# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Caio Hat
"""Progress indicators — 4 variantes para feedback visual de operações longas.

- LinearBar: barra com fração real (downloads, transcribe chunks)
- Spinner: spinner indeterminado com mensagem (carregando modelo)
- StepProgress: chips horizontais com etapa ativa destacada (multi-step)
- IndeterminatePulse: pulso animado para operações sem progresso conhecido
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Pango


class LinearBar(Gtk.Box):
    """Progress bar com label inline (ex: 'Transcrevendo chunk 2/5 · 38%')."""

    def __init__(self, *, show_text: bool = True):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self._label = Gtk.Label(xalign=0)
        self._label.add_css_class("recordo-caption")
        self._label.set_ellipsize(Pango.EllipsizeMode.END)
        if show_text:
            self.append(self._label)
        self._bar = Gtk.ProgressBar()
        self.append(self._bar)

    def set_progress(self, fraction: float, message: str = "") -> None:
        self._bar.set_fraction(max(0.0, min(1.0, fraction)))
        if message:
            self._label.set_text(message)

    def reset(self) -> None:
        self._bar.set_fraction(0.0)
        self._label.set_text("")

    def get_fraction(self) -> float:
        return self._bar.get_fraction()


class Spinner(Gtk.Box):
    """Spinner indeterminado com mensagem ao lado."""

    def __init__(self, message: str = "", *, size: int = 24):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self._spinner = Gtk.Spinner()
        self._spinner.set_size_request(size, size)
        self.append(self._spinner)
        self._label = Gtk.Label(xalign=0)
        self._label.add_css_class("recordo-caption")
        self._label.set_text(message)
        self._label.set_ellipsize(Pango.EllipsizeMode.END)
        self.append(self._label)
        self._spinner.start()

    def set_message(self, message: str) -> None:
        self._label.set_text(message)

    def start(self) -> None:
        self._spinner.start()

    def stop(self) -> None:
        self._spinner.stop()


class StepProgress(Gtk.Box):
    """Chips horizontais com etapa atual destacada.

    Examples:
        >>> sp = StepProgress(['Carregar', 'Converter', 'Transcrever', 'Finalizar'])
        >>> sp.set_active(2)  # marca 'Transcrever' como atual
        >>> sp.set_done(0)    # 'Carregar' done (verde)
        >>> sp.set_done(1)    # 'Converter' done
    """

    def __init__(self, steps: list[str]):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.add_css_class("recordo-step-progress")
        self._chips: list[Gtk.Label] = []
        for s in steps:
            chip = Gtk.Label(label=s)
            chip.add_css_class("chip")
            chip.add_css_class("recordo-caption")
            chip.set_margin_start(2)
            chip.set_margin_end(2)
            self.append(chip)
            self._chips.append(chip)
        self._active_idx: int = -1

    def set_active(self, idx: int) -> None:
        for i, chip in enumerate(self._chips):
            chip.remove_css_class("active")
            if i == idx:
                chip.add_css_class("active")
        self._active_idx = idx

    def set_done(self, idx: int) -> None:
        if 0 <= idx < len(self._chips):
            self._chips[idx].add_css_class("done")
            self._chips[idx].remove_css_class("active")

    def reset(self) -> None:
        for chip in self._chips:
            chip.remove_css_class("active")
            chip.remove_css_class("done")
        self._active_idx = -1


class IndeterminatePulse(Gtk.ProgressBar):
    """ProgressBar pulsing para operações sem progresso conhecido."""

    def __init__(self, message: str = ""):
        super().__init__()
        self._pulse_source_id: int | None = None
        if message:
            self.set_show_text(True)
            self.set_text(message)

    def start(self) -> None:
        from gi.repository import GLib

        if self._pulse_source_id is not None:
            return
        self._pulse_source_id = GLib.timeout_add(150, self._tick)

    def _tick(self) -> bool:
        self.pulse()
        return True

    def stop(self) -> None:
        from gi.repository import GLib

        if self._pulse_source_id is not None:
            GLib.source_remove(self._pulse_source_id)
            self._pulse_source_id = None
        self.set_fraction(0.0)
