# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Caio Hat
"""MarkdownView — WebKit2 carregando HTML renderizado de Markdown."""

from __future__ import annotations

import logging
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, Gtk

from ...markdown_render import RenderOptions, render_file, render_markdown_to_html

log = logging.getLogger(__name__)

# Tenta WebKit 6.0 (GTK4 nativo), fallback pra WebKit2 4.1
_WEBKIT_OK = False
WebKit = None  # type: ignore[assignment]
try:
    gi.require_version("WebKit", "6.0")
    from gi.repository import WebKit  # type: ignore[no-redef]

    _WEBKIT_OK = True
except (ValueError, ImportError):
    try:
        gi.require_version("WebKit2", "4.1")
        from gi.repository import WebKit2 as WebKit  # type: ignore[no-redef]

        _WEBKIT_OK = True
    except (ValueError, ImportError):
        pass


class MarkdownView(Gtk.Box):
    """WebKit-based markdown viewer. Fallback to plain Gtk.TextView quando WebKit ausente."""

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.set_vexpand(True)
        self.set_hexpand(True)
        if _WEBKIT_OK and WebKit is not None:
            self._webview = WebKit.WebView()
            try:
                self._webview.connect("decide-policy", self._on_policy)
            except Exception:
                pass
            self.append(self._webview)
            self._fallback_view = None
        else:
            self._webview = None
            scrolled = Gtk.ScrolledWindow(vexpand=True)
            self._fallback_view = Gtk.TextView()
            self._fallback_view.set_editable(False)
            self._fallback_view.set_monospace(True)
            self._fallback_view.set_wrap_mode(Gtk.WrapMode.WORD)
            scrolled.set_child(self._fallback_view)
            self.append(scrolled)
            log.warning("WebKit indisponível — markdown viewer em modo plain text fallback")

    def _is_dark(self) -> bool:
        try:
            return Adw.StyleManager.get_default().get_dark()
        except Exception:
            return True

    def load_file(self, path: Path) -> None:
        """Carrega arquivo .md/.txt e renderiza."""
        opts = RenderOptions(dark=self._is_dark())
        if self._webview is not None:
            html = render_file(path, opts)
            base_uri = f"file://{path.parent.resolve()}/"
            try:
                self._webview.load_html(html, base_uri)
            except Exception:
                self._webview.load_html(html)
        elif self._fallback_view is not None:
            try:
                text = path.read_text(encoding="utf-8")
            except Exception:
                text = f"(falha ao ler {path})"
            self._fallback_view.get_buffer().set_text(text)

    def load_markdown_text(self, md: str) -> None:
        """Renderiza string markdown diretamente."""
        opts = RenderOptions(dark=self._is_dark())
        if self._webview is not None:
            html = render_markdown_to_html(md, opts)
            try:
                self._webview.load_html(html)
            except Exception:
                pass
        elif self._fallback_view is not None:
            self._fallback_view.get_buffer().set_text(md)

    def _on_policy(self, _wv, decision, decision_type):
        """Intercepta navigations para abrir links externos no browser do sistema."""
        try:
            if hasattr(decision_type, "NAVIGATION_ACTION"):
                nav_type = decision_type.NAVIGATION_ACTION
            else:
                nav_type = 0  # WebKit2 4.1 uses int enum
            if decision_type == nav_type:
                navigation = decision.get_navigation_action()
                req = navigation.get_request()
                uri = req.get_uri() if req else ""
                if uri.startswith(("http://", "https://", "mailto:")):
                    Gio.AppInfo.launch_default_for_uri(uri, None)
                    decision.ignore()
                    return True
        except Exception:
            pass
        return False
