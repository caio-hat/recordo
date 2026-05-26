"""Page Status: card grande com indicador + tempo decorrido + polling 1s.

Calls de socket são async (GLib.Thread + idle_add) pra não travar o main loop
durante operações longas como finalize+concat (timeout até 60s).
"""

from __future__ import annotations

import logging

from gi.repository import GLib, Gtk

from .async_client import call_async
from .widgets.status_card import StatusCard

log = logging.getLogger(__name__)


class StatusPage(Gtk.Box):
    def __init__(self, window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12,
                         margin_top=24, margin_bottom=24, margin_start=24, margin_end=24)
        self.window = window

        self.card = StatusCard()
        self.append(self.card)

        # Help footer
        help_label = Gtk.Label(xalign=0, wrap=True)
        help_label.add_css_class("dim-label")
        help_label.set_markup(
            "<small>Atalho global: <b>Super+R</b> alterna gravação · "
            "<b>Super+Shift+M</b> registra marca.\n"
            "Atualização automática a cada 1s.</small>"
        )
        help_label.set_margin_top(12)
        self.append(help_label)

        # Auto refresh 1s — call assíncrona, não trava UI
        GLib.timeout_add(1000, self._refresh)
        self._refresh()  # initial

    def _refresh(self) -> bool:
        call_async("status", self._on_status)
        return GLib.SOURCE_CONTINUE

    def _on_status(self, resp: dict) -> None:
        if not resp.get("ok"):
            self.card.set_offline(resp.get("error", "?"))
        else:
            self.card.update(resp)
