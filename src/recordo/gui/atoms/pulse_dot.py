# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Caio Hat
"""PulseDot — ponto que pulsa para indicar estado live (ex: gravando)."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk


class PulseDot(Gtk.Box):
    """Box com classes CSS para animação de pulse."""

    def __init__(self, *, size: int = 10):
        super().__init__()
        self.set_size_request(size, size)
        self.add_css_class("recordo-pulse-dot")
        self._active = True

    def set_active(self, active: bool) -> None:
        if active != self._active:
            if active:
                self.add_css_class("recordo-pulse-dot")
            else:
                self.remove_css_class("recordo-pulse-dot")
            self._active = active
