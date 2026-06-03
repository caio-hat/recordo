# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Caio Hat
"""Heading e Caption atoms para hierarquia tipográfica consistente."""

from __future__ import annotations

from typing import Literal

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk

Level = Literal[1, 2, 3]


class Heading(Gtk.Label):
    """Heading hierárquico (h1=page title, h2=section, h3=subsection).

    Mapeia para CSS .recordo-heading-1/2/3.
    """

    def __init__(self, text: str, level: Level = 2):
        super().__init__()
        self.set_text(text)
        self.add_css_class(f"recordo-heading-{level}")
        self.set_xalign(0.0)
        self.set_wrap(True)
        self.set_selectable(False)


class Caption(Gtk.Label):
    """Caption opaco (helper text). Mapeia para .recordo-caption + .dim-label."""

    def __init__(self, text: str):
        super().__init__()
        self.set_text(text)
        self.add_css_class("recordo-caption")
        self.add_css_class("dim-label")
        self.set_xalign(0.0)
        self.set_wrap(True)
        self.set_selectable(False)
