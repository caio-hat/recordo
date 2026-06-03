# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Caio Hat
"""StatusBadge — chip colorido (success/warning/error/info/neutral)."""

from __future__ import annotations

from typing import Literal

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk

Variant = Literal["success", "warning", "error", "info", "neutral"]


class StatusBadge(Gtk.Label):
    """Chip colorido para indicar estado. Usa CSS classes recordo-status-badge.{variant}.

    Examples:
        >>> badge = StatusBadge('success', 'Online')
        >>> badge2 = StatusBadge('warning', '⚠ Sem modelo')
    """

    def __init__(self, variant: Variant, text: str):
        super().__init__()
        self.set_text(text)
        self.add_css_class("recordo-status-badge")
        self.add_css_class(variant)
        self._variant = variant
        self.set_xalign(0.5)
        self.set_valign(Gtk.Align.CENTER)
        self.set_halign(Gtk.Align.START)

    def set_variant(self, variant: Variant) -> None:
        self.remove_css_class(self._variant)
        self.add_css_class(variant)
        self._variant = variant

    def set_status(self, variant: Variant, text: str) -> None:
        self.set_variant(variant)
        self.set_text(text)
