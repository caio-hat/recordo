# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Caio Hat
"""SettingsSubPage — NavigationPage envelope da SettingsPage existente."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

from ..page_settings import SettingsPage


class SettingsSubPage(Adw.NavigationPage):
    """Configurações como NavigationPage filha do Dashboard."""

    def __init__(self, window):
        super().__init__(title="Configurações", tag="settings")
        toolbar = Adw.ToolbarView()
        self.set_child(toolbar)
        toolbar.add_top_bar(Adw.HeaderBar())
        scrolled = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        toolbar.set_content(scrolled)
        self._inner = SettingsPage(window=window)
        scrolled.set_child(self._inner)
