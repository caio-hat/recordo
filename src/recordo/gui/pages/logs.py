# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Caio Hat
"""LogsSubPage — NavigationPage envelope da StatusPage (com tail de logs)."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

from ..page_status import StatusPage


class LogsSubPage(Adw.NavigationPage):
    """Logs/diagnóstico como NavigationPage filha."""

    def __init__(self, window):
        super().__init__(title="Logs e diagnóstico", tag="logs")
        toolbar = Adw.ToolbarView()
        self.set_child(toolbar)
        toolbar.add_top_bar(Adw.HeaderBar())
        scrolled = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        toolbar.set_content(scrolled)
        self._inner = StatusPage(window=window)
        scrolled.set_child(self._inner)
