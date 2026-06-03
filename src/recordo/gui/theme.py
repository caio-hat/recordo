"""Recordo GTK4 theme loader — carrega theme.css e observa dark/light."""

from __future__ import annotations

import logging
from pathlib import Path

from gi.repository import Adw, Gdk, Gtk

log = logging.getLogger(__name__)
CSS_PATH = Path(__file__).parent / "theme.css"

_provider: Gtk.CssProvider | None = None


def install_theme(display: Gdk.Display | None = None) -> Gtk.CssProvider:
    """Carrega theme.css globalmente. Idempotente (safe to call várias vezes).

    Adiciona observador no Adw.StyleManager para responder a mudanças dark/light.
    """
    global _provider
    if _provider is not None:
        return _provider
    display = display or Gdk.Display.get_default()
    _provider = Gtk.CssProvider()
    try:
        _provider.load_from_path(str(CSS_PATH))
    except Exception:
        log.exception("falha ao carregar theme.css")
    Gtk.StyleContext.add_provider_for_display(display, _provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    sm = Adw.StyleManager.get_default()
    sm.connect(
        "notify::dark",
        lambda *_: log.debug("color scheme changed: dark=%s", sm.get_dark()),
    )
    return _provider


def is_dark() -> bool:
    """Retorna True se o tema atual é dark."""
    return Adw.StyleManager.get_default().get_dark()
