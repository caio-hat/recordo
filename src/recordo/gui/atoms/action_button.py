# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Caio Hat
"""ActionButton padronizado com variantes primary/secondary/danger/flat."""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk

Variant = Literal["primary", "secondary", "danger", "flat"]

_VARIANT_CSS = {
    "primary": "suggested-action",
    "secondary": "",
    "danger": "destructive-action",
    "flat": "flat",
}


class ActionButton(Gtk.Button):
    """Botão padronizado. Garante consistência visual através do app.

    Examples:
        >>> btn = ActionButton('Salvar', variant='primary')
        >>> btn.connect('clicked', on_save)
        >>> btn2 = ActionButton('Cancelar', variant='flat')
    """

    def __init__(
        self,
        label: str,
        *,
        variant: Variant = "secondary",
        icon_name: str | None = None,
        on_click: Callable | None = None,
        tooltip: str | None = None,
    ):
        super().__init__()
        css = _VARIANT_CSS.get(variant)
        if css:
            self.add_css_class(css)
        if icon_name and label:
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            box.append(Gtk.Image.new_from_icon_name(icon_name))
            box.append(Gtk.Label(label=label))
            self.set_child(box)
        elif icon_name:
            self.set_icon_name(icon_name)
        else:
            self.set_label(label)
        if tooltip:
            self.set_tooltip_text(tooltip)
        if on_click:
            self.connect("clicked", lambda *_: on_click())
