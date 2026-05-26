"""Recordo Desktop — Adw.Application com sidebar + ViewStack."""

from __future__ import annotations

import logging
import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio, Gtk  # noqa: E402

from .. import __version__  # noqa: E402
from .page_control import ControlPage  # noqa: E402
from .page_settings import SettingsPage  # noqa: E402
from .page_status import StatusPage  # noqa: E402
from .page_transcribe import TranscribePage  # noqa: E402

log = logging.getLogger(__name__)

APP_ID = "io.github.caiohat.Recordo"


class RecordoWindow(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application):
        super().__init__(application=app, title="Recordo")
        self.set_default_size(960, 640)
        self.set_size_request(720, 480)

        # Toast overlay pra feedback
        self.toast_overlay = Adw.ToastOverlay()
        self.set_content(self.toast_overlay)

        split = Adw.NavigationSplitView()
        self.toast_overlay.set_child(split)

        # ── Sidebar ──────────────────────────────────────────────────────────
        sidebar_page = Adw.NavigationPage()
        sidebar_page.set_title("Recordo")
        sidebar_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        sidebar_page.set_child(sidebar_box)

        header_sidebar = Adw.HeaderBar()
        sidebar_box.append(header_sidebar)

        scrolled = Gtk.ScrolledWindow(vexpand=True)
        sidebar_box.append(scrolled)

        self.listbox = Gtk.ListBox()
        self.listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.listbox.add_css_class("navigation-sidebar")
        scrolled.set_child(self.listbox)

        for icon, label, tag in [
            ("media-record-symbolic", "Status", "status"),
            ("media-playback-start-symbolic", "Controle", "control"),
            ("emblem-system-symbolic", "Configurações", "settings"),
            ("document-edit-symbolic", "Transcrever", "transcribe"),
        ]:
            row = Gtk.ListBoxRow()
            row_box = Gtk.Box(
                orientation=Gtk.Orientation.HORIZONTAL,
                spacing=8,
                margin_start=12,
                margin_end=12,
                margin_top=8,
                margin_bottom=8,
            )
            row_box.append(Gtk.Image.new_from_icon_name(icon))
            row_box.append(Gtk.Label(label=label, xalign=0, hexpand=True))
            row.set_child(row_box)
            row.tag = tag  # type: ignore[attr-defined]
            self.listbox.append(row)

        split.set_sidebar(sidebar_page)

        # ── Content ──────────────────────────────────────────────────────────
        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)

        self.status_page = StatusPage(window=self)
        self.control_page = ControlPage(window=self)
        self.settings_page = SettingsPage(window=self)
        self.transcribe_page = TranscribePage(window=self)

        self.stack.add_named(self.status_page, "status")
        self.stack.add_named(self.control_page, "control")
        self.stack.add_named(self.settings_page, "settings")
        self.stack.add_named(self.transcribe_page, "transcribe")

        content_page = Adw.NavigationPage()
        content_page.set_title("Recordo")
        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        content_page.set_child(content_box)

        header_content = Adw.HeaderBar()
        # Menu hambúrguer
        menu = Gio.Menu()
        menu.append("Sobre Recordo", "app.about")
        menu.append("Encerrar daemon", "app.quit-daemon")
        menu_btn = Gtk.MenuButton()
        menu_btn.set_icon_name("open-menu-symbolic")
        menu_btn.set_menu_model(menu)
        header_content.pack_end(menu_btn)
        content_box.append(header_content)

        content_box.append(self.stack)
        split.set_content(content_page)

        self.listbox.connect("row-selected", self._on_row_selected)
        self.listbox.select_row(self.listbox.get_row_at_index(0))

    def _on_row_selected(self, listbox: Gtk.ListBox, row: Gtk.ListBoxRow) -> None:
        if not row:
            return
        self.stack.set_visible_child_name(row.tag)  # type: ignore[attr-defined]

    def toast(self, msg: str, timeout: int = 3) -> None:
        """Adw.Toast pra feedback dentro da janela."""
        t = Adw.Toast.new(msg)
        t.set_timeout(timeout)
        self.toast_overlay.add_toast(t)


class RecordoApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.create_action("about", self._show_about)
        self.create_action("quit-daemon", self._quit_daemon)
        self.window: RecordoWindow | None = None

    def do_activate(self):
        if not self.window:
            self.window = RecordoWindow(self)
        self.window.present()

    def create_action(self, name: str, callback) -> None:
        action = Gio.SimpleAction.new(name, None)
        action.connect("activate", callback)
        self.add_action(action)

    def _show_about(self, *_):
        if not self.window:
            return
        about = Adw.AboutWindow(
            transient_for=self.window,
            modal=True,
            application_name="Recordo",
            application_icon="recordo",
            developer_name="Caio Hat",
            version=__version__,
            comments="Gravador de reuniões fricção-zero · record + recordar",
            website="https://github.com/caio-hat/recordo",
            issue_url="https://github.com/caio-hat/recordo/issues",
            license_type=Gtk.License.MIT_X11,
        )
        about.present()

    def _quit_daemon(self, *_):
        from .async_client import call_async

        def on_resp(resp: dict) -> None:
            if self.window:
                self.window.toast(f"Daemon: {resp.get('shutting_down') or resp.get('error', '?')}")

        call_async("quit", on_resp)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    # Cinnamon detecção: força tema dark se gtk-theme aponta pra *-Dark*
    style_mgr = Adw.StyleManager.get_default()
    style_mgr.set_color_scheme(Adw.ColorScheme.PREFER_DARK)
    app = RecordoApp()
    # Não repassar sys.argv: nossos flags (--gui etc) já foram consumidos pelo
    # argparse do cli.py. GTK Application não reconhece e aborta com
    # "Opção --gui desconhecida". Passamos só o argv0 pra preservar o nome
    # do processo na lista de aplicações.
    return app.run([sys.argv[0]])


if __name__ == "__main__":
    sys.exit(main())
