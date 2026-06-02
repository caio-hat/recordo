"""Recordo Desktop — Adw.Application com sidebar + ViewStack + visual tapeado."""

from __future__ import annotations

import logging
import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, Gio, Gtk  # noqa: E402

from .. import __version__  # noqa: E402
from .page_control import ControlPage  # noqa: E402
from .page_models import ModelsPage  # noqa: E402
from .page_settings import SettingsPage  # noqa: E402
from .page_status import StatusPage  # noqa: E402
from .page_transcribe import TranscribePage  # noqa: E402

log = logging.getLogger(__name__)

APP_ID = "io.github.caiohat.Recordo"


# CSS custom para tapa visual: cards, cores, espaçamento, sidebar moderna
_CUSTOM_CSS = """
/* Sidebar moderna com gradiente sutil */
.navigation-sidebar {
    background: alpha(@accent_bg_color, 0.05);
    padding: 6px;
}

.navigation-sidebar > row {
    border-radius: 8px;
    margin: 2px 0;
    padding: 10px 12px;
    transition: all 200ms ease;
}

.navigation-sidebar > row:selected {
    background: @accent_bg_color;
    color: @accent_fg_color;
    font-weight: bold;
}

.navigation-sidebar > row:hover:not(:selected) {
    background: alpha(@accent_bg_color, 0.15);
}

/* Cards com sombra sutil e cantos arredondados */
.recordo-card {
    background: @card_bg_color;
    border-radius: 12px;
    padding: 16px;
    border: 1px solid alpha(@borders, 0.5);
}

/* Botões de ação primária maiores */
button.pill.suggested-action {
    padding: 12px 24px;
    border-radius: 999px;
    font-weight: bold;
    min-height: 44px;
}

button.pill.destructive-action {
    padding: 12px 24px;
    border-radius: 999px;
    min-height: 44px;
}

/* Status indicator (recording dot) com cor de erro */
.recordo-recording-dot {
    color: @error_color;
    font-weight: bold;
}

/* A1: Daemon status indicator */
.daemon-status {
    font-size: 16pt;
    margin: 0 6px;
}
.daemon-status.success {
    color: @success_color;
}
.daemon-status.error {
    color: @error_color;
}

/* Header bar mais limpa */
headerbar {
    min-height: 48px;
    padding: 0 8px;
}

/* Title com mais peso */
.recordo-title {
    font-size: 18pt;
    font-weight: bold;
    color: @accent_color;
}

.recordo-subtitle {
    font-size: 11pt;
    color: @dim_label;
}

/* PreferencesGroup spacing melhor */
preferencesgroup {
    margin: 12px 0;
}

/* EntryRow com altura mais confortável */
row.entry {
    min-height: 52px;
}

/* D2: Visual consistency — typography e spacing padronizados */

/* Páginas: header titles consistentes */
.title-1 {
    font-size: 20pt;
    font-weight: bold;
    margin-bottom: 4px;
}
.title-2 {
    font-size: 16pt;
    font-weight: bold;
}

/* Cards: hover sutil em ações + transition smooth */
.card {
    border-radius: 12px;
    transition: all 200ms ease;
}

/* PreferencesGroup: spacing entre groups */
preferencesgroup + preferencesgroup {
    margin-top: 18px;
}

/* Botões em listas (action_box dentro de ActionRow): hover claro */
listrow button.flat:hover {
    background: alpha(@accent_bg_color, 0.15);
}

/* Success/Error labels com cor + peso visível */
label.success {
    color: @success_color;
    font-weight: 500;
}
label.error {
    color: @error_color;
    font-weight: 500;
}

/* Monospace label (timestamps, log): mesma fonte sistema */
label.monospace {
    font-family: monospace;
    font-size: 10pt;
}

/* TextView do log: background levemente diferente para destacar */
.card textview {
    background: alpha(@card_bg_color, 0.6);
    border-radius: 8px;
    font-size: 9pt;
}

/* Botões do toggle no Control: shadow leve */
button.pill.suggested-action,
button.pill.destructive-action {
    box-shadow: 0 2px 6px alpha(@theme_fg_color, 0.15);
}

/* Highlighted segment in transcript view */
listrow.accent {
    background: alpha(@accent_bg_color, 0.2);
    border-left: 3px solid @accent_color;
}
"""


class RecordoWindow(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application):
        super().__init__(application=app, title="Recordo")
        self.set_default_size(1024, 700)
        self.set_size_request(800, 540)

        # Toast overlay
        self.toast_overlay = Adw.ToastOverlay()
        self.set_content(self.toast_overlay)

        # Split view sidebar/content
        split = Adw.NavigationSplitView()
        split.set_sidebar_width_fraction(0.22)
        self.toast_overlay.set_child(split)

        # ── Sidebar ──────────────────────────────────────────────────────────
        sidebar_page = Adw.NavigationPage()
        sidebar_page.set_title("Recordo")
        sidebar_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        sidebar_page.set_child(sidebar_box)

        header_sidebar = Adw.HeaderBar()
        # Logo + título no header da sidebar
        title_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        title_box.append(Gtk.Image.new_from_icon_name("recordo-symbolic"))
        title_label = Gtk.Label(label="Recordo")
        title_label.add_css_class("recordo-title")
        title_box.append(title_label)
        header_sidebar.set_title_widget(title_box)
        sidebar_box.append(header_sidebar)

        scrolled = Gtk.ScrolledWindow(vexpand=True)
        sidebar_box.append(scrolled)

        self.listbox = Gtk.ListBox()
        self.listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.listbox.add_css_class("navigation-sidebar")
        scrolled.set_child(self.listbox)

        # Items da sidebar com ícones + descrição opcional
        sidebar_items = [
            ("media-record-symbolic", "Status", "status", "Indicador live + tempo"),
            ("media-playback-start-symbolic", "Controle", "control", "Iniciar/parar/marcar"),
            ("document-edit-symbolic", "Transcrever", "transcribe", "Re-transcrever notas"),
            ("application-x-addon-symbolic", "Modelos", "models", "Baixar/remover modelos"),
            ("emblem-system-symbolic", "Configurações", "settings", "Backends + API keys"),
        ]
        for icon, label, tag, _subtitle in sidebar_items:
            row = Gtk.ListBoxRow()
            row_box = Gtk.Box(
                orientation=Gtk.Orientation.HORIZONTAL,
                spacing=12,
                margin_start=4,
                margin_end=4,
                margin_top=4,
                margin_bottom=4,
            )
            row_box.append(Gtk.Image.new_from_icon_name(icon))
            row_box.append(Gtk.Label(label=label, xalign=0, hexpand=True))
            row.set_child(row_box)
            row.tag = tag  # type: ignore[attr-defined]
            self.listbox.append(row)

        # Footer da sidebar — versão + status daemon (futuro)
        footer_box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=4,
            margin_start=12,
            margin_end=12,
            margin_top=8,
            margin_bottom=12,
        )
        version_label = Gtk.Label(label=f"v{__version__}")
        version_label.add_css_class("dim-label")
        version_label.add_css_class("caption")
        version_label.set_xalign(0)
        version_label.set_hexpand(True)
        footer_box.append(version_label)
        sidebar_box.append(footer_box)

        split.set_sidebar(sidebar_page)

        # ── Content ──────────────────────────────────────────────────────────
        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.stack.set_transition_duration(200)

        self.status_page = StatusPage(window=self)
        self.control_page = ControlPage(window=self)
        self.settings_page = SettingsPage(window=self)
        self.transcribe_page = TranscribePage(window=self)
        self.models_page = ModelsPage(window=self)

        self.stack.add_named(self.status_page, "status")
        self.stack.add_named(self.control_page, "control")
        self.stack.add_named(self.settings_page, "settings")
        self.stack.add_named(self.transcribe_page, "transcribe")
        self.stack.add_named(self.models_page, "models")

        content_page = Adw.NavigationPage()
        content_page.set_title("Recordo")
        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        content_page.set_child(content_box)

        header_content = Adw.HeaderBar()

        # Botão "Nova gravação" rápido (toggle) no header esquerdo
        self.btn_quick_toggle = Gtk.Button()
        toggle_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        toggle_box.append(Gtk.Image.new_from_icon_name("media-record-symbolic"))
        toggle_box.append(Gtk.Label(label="Gravar"))
        self.btn_quick_toggle.set_child(toggle_box)
        self.btn_quick_toggle.add_css_class("suggested-action")
        self.btn_quick_toggle.set_tooltip_text("Iniciar/parar gravação (Super+R)")
        self.btn_quick_toggle.connect("clicked", self._on_quick_toggle)
        header_content.pack_start(self.btn_quick_toggle)

        # Botão abrir ~/Notas no header
        btn_notas = Gtk.Button(icon_name="folder-symbolic")
        btn_notas.set_tooltip_text("Abrir ~/Notas/")
        btn_notas.connect("clicked", self._on_open_notas)
        header_content.pack_start(btn_notas)

        # Indicador de status do daemon (A1) — bullet verde/vermelho
        self.daemon_status_label = Gtk.Label(label="●")
        self.daemon_status_label.set_tooltip_text("Daemon: verificando...")
        self.daemon_status_label.add_css_class("daemon-status")
        self.daemon_status_label.add_css_class("dim-label")
        header_content.pack_end(self.daemon_status_label)

        # Menu hambúrguer (direito)
        menu = Gio.Menu()
        menu.append("Sobre Recordo", "app.about")
        menu.append("Recarregar config", "app.reload-config")
        # A1: Daemon control submenu
        daemon_menu = Gio.Menu()
        daemon_menu.append("Iniciar daemon", "app.start-daemon")
        daemon_menu.append("Reiniciar daemon", "app.restart-daemon")
        daemon_menu.append("Encerrar daemon", "app.quit-daemon")
        menu.append_submenu("Daemon", daemon_menu)
        menu_btn = Gtk.MenuButton()
        menu_btn.set_icon_name("open-menu-symbolic")
        menu_btn.set_menu_model(menu)
        header_content.pack_end(menu_btn)

        content_box.append(header_content)
        content_box.append(self.stack)
        split.set_content(content_page)

        self.listbox.connect("row-selected", self._on_row_selected)
        self.listbox.select_row(self.listbox.get_row_at_index(0))

        # A1: polling do status do daemon a cada 3s para atualizar indicador
        from gi.repository import GLib

        self._update_daemon_status()  # primeira chamada imediata
        GLib.timeout_add_seconds(3, self._update_daemon_status_periodic)

    def _update_daemon_status_periodic(self) -> bool:
        """Callback do GLib timeout — sempre retorna True para manter polling."""
        self._update_daemon_status()
        return True  # keep timer

    def _update_daemon_status(self) -> None:
        """Atualiza indicador visual baseado em is_daemon_alive() (A1)."""
        from .. import client as client_mod

        try:
            alive = client_mod.is_daemon_alive()
        except Exception:
            alive = False

        if alive:
            self.daemon_status_label.set_label("●")
            self.daemon_status_label.set_tooltip_text("Daemon: ativo")
            self.daemon_status_label.remove_css_class("error")
            self.daemon_status_label.remove_css_class("dim-label")
            self.daemon_status_label.add_css_class("success")
        else:
            self.daemon_status_label.set_label("●")
            self.daemon_status_label.set_tooltip_text("Daemon: inativo (clique no menu para iniciar)")
            self.daemon_status_label.remove_css_class("success")
            self.daemon_status_label.remove_css_class("dim-label")
            self.daemon_status_label.add_css_class("error")

    def _on_row_selected(self, _listbox: Gtk.ListBox, row: Gtk.ListBoxRow) -> None:
        if not row:
            return
        self.stack.set_visible_child_name(row.tag)  # type: ignore[attr-defined]

    def _on_quick_toggle(self, _btn) -> None:
        from .async_client import call_async

        def on_resp(resp: dict) -> None:
            if resp.get("ok"):
                msg = resp.get("subject") or resp.get("target_dir") or "Toggle OK"
                self.toast(f"✓ {msg}")
            else:
                self.toast(f"⚠ {resp.get('error', '?')}")

        call_async("toggle", on_resp)

    @staticmethod
    def _on_open_notas(_btn) -> None:
        import subprocess
        from pathlib import Path

        notas = Path.home() / "Notas"
        notas.mkdir(parents=True, exist_ok=True)
        try:
            subprocess.Popen(
                ["xdg-open", str(notas)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            log.warning("xdg-open não disponível")

    def toast(self, msg: str, timeout: int = 3) -> None:
        t = Adw.Toast.new(msg)
        t.set_timeout(timeout)
        self.toast_overlay.add_toast(t)


class RecordoApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.create_action("about", self._show_about)
        self.create_action("quit-daemon", self._quit_daemon)
        self.create_action("start-daemon", self._start_daemon)
        self.create_action("restart-daemon", self._restart_daemon)
        self.create_action("reload-config", self._reload_config)
        self.window: RecordoWindow | None = None

    def do_activate(self):
        # Aplica CSS custom uma vez
        css = Gtk.CssProvider()
        css.load_from_data(_CUSTOM_CSS.encode("utf-8"))
        display = Gdk.Display.get_default()
        if display:
            Gtk.StyleContext.add_provider_for_display(display, css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

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
            comments=(
                "Gravador de reuniões fricção-zero · record + recordar.\n\n"
                "Backends de transcrição: Whisper (local), Parakeet TDT v3 (NeMo),\n"
                "Cohere Transcribe (#1 Open ASR Leaderboard 2026).\n\n"
                "Resumo via LLM: Ollama (local + remoto), Gemini, OpenAI, Anthropic,\n"
                "Groq/OpenAI-compat. Cascata fallback automática."
            ),
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
                # Atualiza indicador imediato (não esperar o polling 3s)
                from gi.repository import GLib

                GLib.timeout_add(500, lambda: (self.window._update_daemon_status(), False)[1])

        call_async("quit", on_resp)

    def _start_daemon(self, *_):
        """A1: inicia daemon via client.ensure_daemon (systemd ou spawn)."""
        from gi.repository import GLib

        from .. import client as client_mod

        if not self.window:
            return

        if client_mod.is_daemon_alive():
            self.window.toast("Daemon já está ativo")
            return

        self.window.toast("Iniciando daemon...")

        def _do_start():
            ok = client_mod.ensure_daemon()
            GLib.idle_add(self._on_daemon_started, ok)
            return False  # remove from idle queue

        # Off main loop para não bloquear UI
        import threading

        threading.Thread(target=_do_start, daemon=True).start()

    def _on_daemon_started(self, ok: bool) -> None:
        if not self.window:
            return
        if ok:
            self.window.toast("✓ Daemon iniciado")
        else:
            self.window.toast("⚠ Falha ao iniciar daemon — veja logs")
        self.window._update_daemon_status()

    def _restart_daemon(self, *_):
        """A1: encerra daemon, espera, reinicia."""
        from gi.repository import GLib

        from .. import client as client_mod
        from .async_client import call_async

        if not self.window:
            return

        self.window.toast("Reiniciando daemon...")

        def on_quit_resp(_resp: dict) -> None:
            # Aguarda 1.5s para o socket sumir, depois ensure_daemon
            def _do_restart():
                import time

                # Espera socket fechar (até 5s)
                for _ in range(20):
                    if not client_mod.is_daemon_alive():
                        break
                    time.sleep(0.25)
                ok = client_mod.ensure_daemon()
                GLib.idle_add(self._on_daemon_restarted, ok)
                return False

            import threading

            threading.Thread(target=_do_restart, daemon=True).start()

        call_async("quit", on_quit_resp)

    def _on_daemon_restarted(self, ok: bool) -> None:
        if not self.window:
            return
        self.window.toast("✓ Daemon reiniciado" if ok else "⚠ Falha no restart")
        self.window._update_daemon_status()

    def _reload_config(self, *_):
        from .async_client import call_async

        def on_resp(resp: dict) -> None:
            if not self.window:
                return
            if resp.get("ok"):
                changes = resp.get("changes") or ["sem mudanças"]
                self.window.toast(f"✓ Config recarregada · {len(changes)} mudança(s)")
            else:
                self.window.toast(f"⚠ {resp.get('error', '?')}")

        call_async("reload_config", on_resp)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    style_mgr = Adw.StyleManager.get_default()
    style_mgr.set_color_scheme(Adw.ColorScheme.PREFER_DARK)
    app = RecordoApp()
    return app.run([sys.argv[0]])


if __name__ == "__main__":
    sys.exit(main())
