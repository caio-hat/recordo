# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Caio Hat
"""EmptyState — placeholder para listas/seções vazias."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk

from ..atoms import ActionButton, Caption, Heading


class EmptyState(Gtk.Box):
    """Tela/seção vazia com ícone, título, descrição e botão opcional.

    Examples:
        >>> e = EmptyState(
        ...     icon='folder-symbolic',
        ...     title='Sem gravações',
        ...     description='Aperte Super+R para gravar a primeira reunião',
        ...     action_label='Gravar agora',
        ...     on_action=lambda: print('rec'),
        ... )
    """

    def __init__(
        self,
        *,
        icon: str = "folder-symbolic",
        title: str,
        description: str = "",
        action_label: str | None = None,
        on_action=None,
    ):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.add_css_class("recordo-empty-state")
        self.set_halign(Gtk.Align.CENTER)
        self.set_valign(Gtk.Align.CENTER)

        # icon (large)
        img = Gtk.Image.new_from_icon_name(icon)
        img.set_pixel_size(64)
        img.add_css_class("recordo-empty-icon")
        img.set_halign(Gtk.Align.CENTER)
        self.append(img)

        # title
        h = Heading(title, level=2)
        h.set_xalign(0.5)
        h.set_halign(Gtk.Align.CENTER)
        self.append(h)

        # description
        if description:
            cap = Caption(description)
            cap.set_xalign(0.5)
            cap.set_halign(Gtk.Align.CENTER)
            cap.set_max_width_chars(50)
            self.append(cap)

        # optional action
        if action_label and on_action:
            btn = ActionButton(action_label, variant="primary", on_click=on_action)
            btn.set_halign(Gtk.Align.CENTER)
            btn.set_margin_top(12)
            self.append(btn)
