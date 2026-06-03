# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Caio Hat
"""Recordo GUI — entrypoint Adw.Application + main window.

v0.2.4 redesign: substitui sidebar de 5 abas por Adw.NavigationView root com
DashboardPage como home. Sub-pages (Settings/Models/Logs/RecordingDetail) são
empurradas via push() e o usuário navega com botão back nativo do header.

OnboardingWizard aparece em first_run.
"""

from __future__ import annotations

import logging
import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, Gio, Gtk

from .. import __version__
from ..config import load_config
from .pages import (
    DashboardPage,
    LogsSubPage,
    ModelsSubPage,
    RecordingDetailPage,
    SettingsSubPage,
)
from .theme import install_theme
from .wizards import OnboardingWizard, should_show_onboarding

log = logging.getLogger(__name__)

APP_ID = "io.github.caiohat.Recordo"


class RecordoWindow(Adw.ApplicationWindow):
    """Main window — Adw.NavigationView com DashboardPage como root."""

    def __init__(self, app: Adw.Application):
        super().__init__(application=app, title="Recordo")
        self.set_default_size(960, 720)
        self.set_size_request(720, 540)

        # Toast overlay envolve tudo
        self.toast_overlay = Adw.ToastOverlay()
        self.set_content(self.toast_overlay)

        # Root NavigationView
        self.nav_view = Adw.NavigationView()
        self.toast_overlay.set_child(self.nav_view)

        # Dashboard como root page
        self.dashboard = DashboardPage(
            on_open_settings=self._open_settings,
            on_open_models=self._open_models,
            on_open_logs=self._open_logs,
            on_open_recording=self._open_recording,
        )
        self.nav_view.add(self.dashboard)

        # Daemon status periodic update (compatibilidade com código antigo)
        from gi.repository import GLib

        GLib.timeout_add_seconds(3, self._update_daemon_status_periodic)

    # ------------------------------------------------------------------
    # Navigation handlers
    # ------------------------------------------------------------------

    def _open_settings(self) -> None:
        page = SettingsSubPage(window=self)
        self.nav_view.push(page)

    def _open_models(self) -> None:
        page = ModelsSubPage(window=self)
        self.nav_view.push(page)

    def _open_logs(self) -> None:
        page = LogsSubPage(window=self)
        self.nav_view.push(page)

    def _open_recording(self, rec_dir) -> None:
        page = RecordingDetailPage(rec_dir)
        self.nav_view.push(page)

    # ------------------------------------------------------------------
    # Toast helper
    # ------------------------------------------------------------------

    def toast(self, msg: str, timeout: int = 3) -> None:
        t = Adw.Toast.new(msg)
        t.set_timeout(timeout)
        self.toast_overlay.add_toast(t)

    def refresh_after_reload(self) -> None:
        """Chamado após reload_config — re-renderiza dashboard.

        v0.2.3: TranscribePage tinha refresh_backend_card; agora é dashboard
        que chama refresh dos próprios componentes.
        """
        try:
            if hasattr(self.dashboard, "_refresh_status"):
                self.dashboard._refresh_status()
            if hasattr(self.dashboard, "_refresh_recordings"):
                self.dashboard._refresh_recordings()
        except Exception:
            log.exception("refresh_after_reload falhou")

    # ------------------------------------------------------------------
    # Daemon status periodic (delegate ao dashboard que já implementa)
    # ------------------------------------------------------------------

    def _update_daemon_status_periodic(self) -> bool:
        try:
            self.dashboard._refresh_status()
        except Exception:
            pass
        return True

    def _update_daemon_status(self) -> None:
        """Compatibilidade com código que chamava _update_daemon_status."""
        try:
            self.dashboard._refresh_status()
        except Exception:
            pass


class RecordoApp(Adw.Application):
    def __init__(self):
        super().__init__(
            application_id=APP_ID,
            flags=Gio.ApplicationFlags.FLAGS_NONE,
        )
        self.window: RecordoWindow | None = None

    def do_activate(self):
        # CSS theme global (idempotente)
        install_theme(Gdk.Display.get_default())

        # Janela ou foca existente
        if self.window is None:
            self.window = RecordoWindow(self)

        self.window.present()

        # Onboarding wizard se first_run
        try:
            cfg = load_config()
            if should_show_onboarding(cfg):
                wizard = OnboardingWizard(
                    on_complete=self._on_wizard_complete,
                    parent=self.window,
                )
                wizard.present()
        except Exception:
            log.exception("falha ao avaliar onboarding")

        # Actions globais (acessadas via menu hamburger no Dashboard)
        self.create_action("restart-daemon", self._restart_daemon)
        self.create_action("reload-config", self._reload_config)
        self.create_action("about", self._show_about)
        self.create_action("quit", self._quit_app)
        self.set_accels_for_action("app.quit", ["<primary>q"])
        self.set_accels_for_action("app.about", ["F1"])

    def create_action(self, name: str, callback) -> None:
        action = Gio.SimpleAction.new(name, None)
        action.connect("activate", callback)
        self.add_action(action)

    def _on_wizard_complete(self, chosen_backend: str | None) -> None:
        if self.window is None:
            return
        if chosen_backend:
            self.window.toast(f"✓ Backend definido: {chosen_backend}")
        else:
            self.window.toast("Onboarding pulado — configure depois em Configurações")

    def _quit_app(self, *_):
        if self.window is not None:
            self.window.close()
        self.quit()

    def _show_about(self, *_):
        dialog = Adw.AboutWindow(
            transient_for=self.window,
            application_name="Recordo",
            application_icon=APP_ID,
            developer_name="Caio Hat",
            version=__version__,
            comments=(
                "Gravador de reuniões fricção-zero para Linux (TDAH-friendly).\n"
                "Trocadilho: record (gravar) + recordar (lembrar)."
            ),
            website="https://github.com/caio-hat/recordo",
            issue_url="https://github.com/caio-hat/recordo/issues",
            copyright="© 2026 Caio Hat",
            license_type=Gtk.License.GPL_3_0_ONLY,
        )
        dialog.present()

    # ------------------------------------------------------------------
    # Daemon control actions
    # ------------------------------------------------------------------

    def _quit_daemon(self, *_):
        from .async_client import call_async

        def on_resp(resp: dict) -> None:
            if not self.window:
                return
            self.window.toast("✓ Daemon encerrado" if resp.get("ok") else f"⚠ {resp.get('error', '?')}")

        call_async("quit", on_resp)

    def _start_daemon(self, *_):
        if not self.window:
            return
        self.window.toast("Iniciando daemon...")
        from gi.repository import GLib

        from .. import client as client_mod

        def worker():
            ok = client_mod.ensure_daemon()
            GLib.idle_add(self._on_daemon_started, ok)
            return False

        import threading

        threading.Thread(target=worker, daemon=True).start()

    def _on_daemon_started(self, ok: bool) -> None:
        if not self.window:
            return
        self.window.toast("✓ Daemon iniciado" if ok else "⚠ Falha ao iniciar")
        self.window._update_daemon_status()

    def _restart_daemon(self, *_):
        """v0.2.2/v0.2.3: encerra daemon, espera, reinicia + dialog de erro."""
        from gi.repository import GLib

        from .. import client as client_mod
        from .async_client import call_async

        if not self.window:
            return

        self.window.toast("Reiniciando daemon...")

        def on_quit_resp(_resp: dict) -> None:
            def _do_restart():
                import time

                socket_closed = False
                for _ in range(20):
                    if not client_mod.is_daemon_alive():
                        socket_closed = True
                        break
                    time.sleep(0.25)

                from ..config import SOCKET_PATH

                if SOCKET_PATH.exists() and not client_mod.is_daemon_alive():
                    try:
                        SOCKET_PATH.unlink()
                    except OSError:
                        pass

                ok = client_mod.ensure_daemon()
                err_detail = (
                    ""
                    if ok
                    else (
                        f"ensure_daemon retornou False após quit. socket_closed={socket_closed}. "
                        "Veja /tmp/recordo.daemon.log para detalhes."
                    )
                )
                GLib.idle_add(self._on_daemon_restarted, ok, err_detail)
                return False

            import threading

            threading.Thread(target=_do_restart, daemon=True).start()

        call_async("quit", on_quit_resp)

    def _on_daemon_restarted(self, ok: bool, err_detail: str = "") -> None:
        if not self.window:
            return
        if ok:
            self.window.toast("✓ Daemon reiniciado")
        else:
            self.window.toast("⚠ Falha no restart")
            self._show_daemon_error_dialog("Restart falhou", err_detail)
        self.window._update_daemon_status()

    def _show_daemon_error_dialog(self, action: str, detail: str) -> None:
        from html import escape

        title = f"❌ {action}"
        body_lines = [
            "<b>O daemon não respondeu ou falhou ao iniciar.</b>\n",
            "<b>Possíveis causas:</b>",
            "  • Outro processo do daemon ainda finalizando",
            "  • Socket UNIX órfão em /run/user/1000/recordo.sock",
            "  • systemd unit em estado de falha — verifique <tt>systemctl --user status recordo</tt>",
            "  • Erro fatal no código — veja /tmp/recordo.daemon.log",
        ]
        if detail:
            body_lines.append(f"\n<b>Detalhe técnico:</b>\n<tt>{escape(detail)}</tt>")

        body = "\n".join(body_lines)
        dlg = Adw.MessageDialog.new(self.window, title, body)
        dlg.set_body_use_markup(True)
        dlg.add_response("close", "Fechar")
        dlg.add_response("logs", "Abrir log do daemon")
        dlg.set_default_response("close")
        dlg.set_close_response("close")
        dlg.connect("response", self._on_daemon_error_response)
        dlg.present()

    @staticmethod
    def _on_daemon_error_response(_dlg, response: str) -> None:
        if response == "logs":
            import subprocess

            try:
                subprocess.Popen(["xdg-open", "/tmp/recordo.daemon.log"])
            except FileNotFoundError:
                pass

    def _reload_config(self, *_):
        from .async_client import call_async

        def on_resp(resp: dict) -> None:
            if not self.window:
                return
            if resp.get("ok"):
                changes = resp.get("changes") or []
                if changes:
                    self.window.toast(f"✓ Config recarregada · {len(changes)} mudança(s)")
                else:
                    self.window.toast("✓ Config recarregada (sem mudanças)")
                self.window.refresh_after_reload()
            else:
                self.window.toast(f"⚠ {resp.get('error', '?')}")

        call_async("reload_config", on_resp)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    style_mgr = Adw.StyleManager.get_default()
    style_mgr.set_color_scheme(Adw.ColorScheme.PREFER_DARK)
    app = RecordoApp()
    return app.run([sys.argv[0]])
