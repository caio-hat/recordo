# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Caio Hat
"""Card — container com sombra e padding consistentes."""

from __future__ import annotations

from typing import Literal

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk

Variant = Literal["default", "warning", "success", "error", "elevated", "interactive"]


class Card(Gtk.Box):
    """Container card. Use add_child() para adicionar conteúdo.

    Examples:
        >>> c = Card(variant='warning')
        >>> c.add_child(Heading('Atenção', level=2))
        >>> c.add_child(Caption('Modelo não instalado'))
    """

    def __init__(self, variant: Variant = "default", *, spacing: int = 12):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=spacing)
        self.add_css_class("recordo-card")
        if variant != "default":
            self.add_css_class(variant)
        self._variant = variant

    def add_child(self, widget: Gtk.Widget) -> None:
        self.append(widget)

    def set_variant(self, variant: Variant) -> None:
        if self._variant != "default":
            self.remove_css_class(self._variant)
        if variant != "default":
            self.add_css_class(variant)
        self._variant = variant
