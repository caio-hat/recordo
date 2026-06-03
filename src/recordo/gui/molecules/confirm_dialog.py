# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Caio Hat
"""ConfirmDialog — dialog yes/no com callbacks."""

from __future__ import annotations

from collections.abc import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk


class ConfirmDialog:
    """Confirmação yes/no padronizada.

    Uses destructive style por padrão quando danger=True.
    """

    @staticmethod
    def present(
        parent: Gtk.Window | None,
        title: str,
        body: str,
        *,
        confirm_label: str = "Confirmar",
        cancel_label: str = "Cancelar",
        danger: bool = False,
        on_confirm: Callable | None = None,
        on_cancel: Callable | None = None,
    ) -> Adw.MessageDialog:
        dlg = Adw.MessageDialog.new(parent, title, body)
        dlg.add_response("cancel", cancel_label)
        dlg.add_response("confirm", confirm_label)
        if danger:
            dlg.set_response_appearance("confirm", Adw.ResponseAppearance.DESTRUCTIVE)
        else:
            dlg.set_response_appearance("confirm", Adw.ResponseAppearance.SUGGESTED)
        dlg.set_default_response("confirm")
        dlg.set_close_response("cancel")

        def _on_response(_d, response: str):
            if response == "confirm" and on_confirm:
                on_confirm()
            elif response == "cancel" and on_cancel:
                on_cancel()

        dlg.connect("response", _on_response)
        dlg.present()
        return dlg
