"""Async wrapper para send_to_daemon na GUI GTK.

Por que existe: send_to_daemon é blocking (até 60s no timeout do socket pra
casos como finalize+concat de sessão longa). Chamar isso direto no main loop
GTK trava a janela inteira por todo esse tempo. Solução: rodar em thread,
voltar pro main loop com GLib.idle_add pra atualizar UI.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any

from gi.repository import GLib

from ..client import send_to_daemon

log = logging.getLogger(__name__)

# Callback recebe (resp_dict). Erros já viram dict {"ok": False, "error": ...}.
ResponseCallback = Callable[[dict], Any]


def call_async(
    cmd: str,
    callback: ResponseCallback | None = None,
    **kwargs: Any,
) -> None:
    """Spawn de thread daemon que chama send_to_daemon e dispara callback.

    Callback roda no main loop GTK (idle_add), pode atualizar UI com segurança.
    Se callback for None, descarta resposta.

    Uso típico:
        def on_response(resp: dict) -> None:
            if resp.get("ok"):
                self.window.toast(resp.get("subject", "OK"))

        call_async("toggle", on_response)
    """
    def _worker() -> None:
        try:
            resp = send_to_daemon(cmd, **kwargs)
        except Exception as e:
            log.exception("call_async %s falhou", cmd)
            resp = {"ok": False, "error": str(e)}
        if callback is not None:
            GLib.idle_add(callback, resp)

    threading.Thread(
        target=_worker, daemon=True, name=f"recordo-gui-{cmd}",
    ).start()


__all__ = ["ResponseCallback", "call_async"]
