# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Caio Hat
"""InfoDialog — dialog informativo com heading + body + action OK."""

from __future__ import annotations

from html import escape as html_escape

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk


class InfoDialog:
    """Wrapper sobre Adw.MessageDialog para padronizar dialogs informativos.

    Use via: InfoDialog.present(parent, title, body, body_format='plain'|'markup')
    """

    @staticmethod
    def present(
        parent: Gtk.Window | None,
        title: str,
        body: str,
        *,
        body_format: str = "plain",
        action_label: str = "Entendi",
    ) -> Adw.MessageDialog:
        dlg = Adw.MessageDialog.new(parent, title, body)
        if body_format == "markup":
            dlg.set_body_use_markup(True)
        dlg.add_response("ok", action_label)
        dlg.set_default_response("ok")
        dlg.set_close_response("ok")
        dlg.present()
        return dlg

    @staticmethod
    def escape(text: str) -> str:
        """Escapa HTML/Pango markup. Use quando body_format='markup' e o conteúdo é user-provided."""
        return html_escape(text)
