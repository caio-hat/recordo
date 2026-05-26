"""Tray icon do sistema com ações rápidas.

Usa XApp.StatusIcon (idiomático Cinnamon/Mint/MATE/Xfce) com fallback para
AyatanaAppIndicator3 (Ubuntu/GNOME com extension). Roda em processo
independente da GUI principal (que é GTK4) — este módulo usa GTK3 porque
é o que XApp/AppIndicator suportam.

Funcionalidades:
- Ícone muda de cor conforme estado: ⚫ idle, 🔴 recording
- Polling 2s do daemon via socket
- Tooltip mostra estado atual + tempo decorrido
- Menu Gtk com ações rápidas:
    - Status (label desabilitada — "🔴 Gravando · 02:34")
    - ▶ Iniciar / ⏹ Parar gravação (toggle dinâmico)
    - 📍 Marcar momento (apenas se gravando)
    - 🪟 Abrir GUI (recordo --gui)
    - 📂 Abrir ~/Notas (xdg-open)
    - ↻ Recarregar config
    - ⏻ Encerrar daemon
    - ✕ Sair (apenas tray, daemon segue)

Autostart: setup.sh cria ~/.config/autostart/recordo-tray.desktop opcional.

Uso:
    recordo --tray
"""

from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path
from typing import Any

import gi

gi.require_version("Gtk", "3.0")

from gi.repository import GLib, Gtk  # noqa: E402

from .client import send_to_daemon  # noqa: E402

log = logging.getLogger(__name__)

POLL_INTERVAL_MS = 2000  # status refresh
ICON_IDLE = "media-record"
ICON_RECORDING = "media-record"
SYMBOLIC_ICON = "recordo-symbolic"  # icone instalado em hicolor/symbolic/apps/

# ── Backend probe: XApp (preferido) ou Ayatana fallback ─────────────────────
_BACKEND: str = "none"
try:
    gi.require_version("XApp", "1.0")
    from gi.repository import XApp  # type: ignore[import-not-found]

    _BACKEND = "xapp"
except (ValueError, ImportError):
    try:
        gi.require_version("AyatanaAppIndicator3", "0.1")
        from gi.repository import AyatanaAppIndicator3 as AppIndicator  # type: ignore[import-not-found]

        _BACKEND = "ayatana"
    except (ValueError, ImportError):
        log.warning("nem XApp nem AyatanaAppIndicator3 disponíveis — tray indisponível")


class RecordoTray:
    """Tray icon com menu de ações rápidas e polling de status."""

    def __init__(self) -> None:
        self.recording: bool = False
        self.elapsed_seconds: int = 0
        self.subject: str = ""
        self.daemon_alive: bool = False

        self.icon: Any | None = None
        self.menu: Gtk.Menu | None = None
        self.menu_items: dict[str, Gtk.MenuItem] = {}

        self._setup_icon()
        self._build_menu()
        self._refresh_status()
        # Polling
        GLib.timeout_add(POLL_INTERVAL_MS, self._refresh_status)

    def _setup_icon(self) -> None:
        if _BACKEND == "xapp":
            self.icon = XApp.StatusIcon()
            self.icon.set_name("recordo-tray")
            self.icon.set_icon_name(SYMBOLIC_ICON)
            self.icon.set_tooltip_text("Recordo · iniciando…")
            self.icon.set_visible(True)
            self.icon.connect("button-press-event", self._on_click)
        elif _BACKEND == "ayatana":
            self.icon = AppIndicator.Indicator.new(
                "recordo-tray",
                SYMBOLIC_ICON,
                AppIndicator.IndicatorCategory.APPLICATION_STATUS,
            )
            self.icon.set_status(AppIndicator.IndicatorStatus.ACTIVE)
            self.icon.set_title("Recordo")
        else:
            raise RuntimeError(
                "Tray indisponível: instale gir1.2-xapp-1.0 OU gir1.2-ayatanaappindicator3-0.1"
            )

    def _build_menu(self) -> None:
        self.menu = Gtk.Menu()

        # Status label (não-clicável)
        status_item = Gtk.MenuItem(label="⚫ Daemon offline")
        status_item.set_sensitive(False)
        self.menu.append(status_item)
        self.menu_items["status"] = status_item

        self.menu.append(Gtk.SeparatorMenuItem())

        # Toggle gravação
        toggle_item = Gtk.MenuItem(label="▶  Iniciar gravação")
        toggle_item.connect("activate", self._on_toggle)
        self.menu.append(toggle_item)
        self.menu_items["toggle"] = toggle_item

        # Marcar momento (visível só durante gravação)
        mark_item = Gtk.MenuItem(label="📍  Marcar momento")
        mark_item.connect("activate", self._on_mark)
        self.menu.append(mark_item)
        self.menu_items["mark"] = mark_item

        self.menu.append(Gtk.SeparatorMenuItem())

        # Abrir GUI
        gui_item = Gtk.MenuItem(label="🪟  Abrir GUI desktop")
        gui_item.connect("activate", self._on_open_gui)
        self.menu.append(gui_item)
        self.menu_items["gui"] = gui_item

        # Abrir Notas
        notas_item = Gtk.MenuItem(label="📂  Abrir ~/Notas")
        notas_item.connect("activate", self._on_open_notas)
        self.menu.append(notas_item)

        # Reload config
        reload_item = Gtk.MenuItem(label="↻  Recarregar config")
        reload_item.connect("activate", self._on_reload_config)
        self.menu.append(reload_item)

        self.menu.append(Gtk.SeparatorMenuItem())

        # Encerrar daemon
        quit_daemon_item = Gtk.MenuItem(label="⏻  Encerrar daemon")
        quit_daemon_item.connect("activate", self._on_quit_daemon)
        self.menu.append(quit_daemon_item)

        # Sair tray
        quit_item = Gtk.MenuItem(label="✕  Sair (daemon continua)")
        quit_item.connect("activate", self._on_quit_tray)
        self.menu.append(quit_item)

        self.menu.show_all()

        # Conecta menu ao indicator (Ayatana)
        if _BACKEND == "ayatana" and self.icon:
            self.icon.set_menu(self.menu)

    def _on_click(self, icon: Any, event: Any) -> None:
        """XApp: mostra menu no clique."""
        if event.button == 1 or event.button == 3:  # left or right
            self.menu.popup_at_pointer(event)

    # ── Actions ─────────────────────────────────────────────────────────────
    def _on_toggle(self, _item: Gtk.MenuItem) -> None:
        resp = send_to_daemon("toggle")
        if not resp.get("ok"):
            self._notify_error("Toggle", resp.get("error", "?"))

    def _on_mark(self, _item: Gtk.MenuItem) -> None:
        if not self.recording:
            self._notify_error("Marcar", "nenhuma gravação ativa")
            return
        # Dialog simples Gtk pra texto
        dlg = Gtk.Dialog(title="📍 Marcar momento", flags=Gtk.DialogFlags.MODAL)
        dlg.add_button("Cancelar", Gtk.ResponseType.CANCEL)
        dlg.add_button("Marcar", Gtk.ResponseType.OK)
        dlg.set_default_response(Gtk.ResponseType.OK)
        entry = Gtk.Entry()
        entry.set_placeholder_text("ex: decisão importante…")
        entry.set_activates_default(True)
        box = dlg.get_content_area()
        box.set_spacing(8)
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        box.set_margin_start(12)
        box.set_margin_end(12)
        box.add(Gtk.Label(label="Texto opcional (vazio = só timestamp):"))
        box.add(entry)
        dlg.show_all()
        resp = dlg.run()
        text = entry.get_text() if resp == Gtk.ResponseType.OK else None
        dlg.destroy()
        if text is not None:
            send_to_daemon("mark", text=text)

    def _on_open_gui(self, _item: Gtk.MenuItem) -> None:
        try:
            subprocess.Popen(
                ["recordo-gui"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except FileNotFoundError:
            # Fallback: python -m recordo.gui via venv
            try:
                subprocess.Popen(
                    [sys.executable, "-m", "recordo.gui"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
            except OSError as e:
                self._notify_error("GUI", str(e))

    @staticmethod
    def _on_open_notas(_item: Gtk.MenuItem) -> None:
        notas = Path.home() / "Notas"
        if not notas.exists():
            notas.mkdir(parents=True, exist_ok=True)
        try:
            subprocess.Popen(
                ["xdg-open", str(notas)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            log.warning("xdg-open não disponível")

    def _on_reload_config(self, _item: Gtk.MenuItem) -> None:
        resp = send_to_daemon("reload_config")
        if not resp.get("ok"):
            self._notify_error("Reload", resp.get("error", "?"))

    def _on_quit_daemon(self, _item: Gtk.MenuItem) -> None:
        send_to_daemon("quit")

    @staticmethod
    def _on_quit_tray(_item: Gtk.MenuItem) -> None:
        Gtk.main_quit()

    @staticmethod
    def _notify_error(action: str, msg: str) -> None:
        try:
            subprocess.run(
                ["notify-send", "-a", "Recordo", "-u", "critical", f"{action}: {msg}"],
                timeout=2,
                check=False,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            log.warning("[%s] %s", action, msg)

    # ── Status polling ──────────────────────────────────────────────────────
    def _refresh_status(self) -> bool:
        resp = send_to_daemon("status")
        self.daemon_alive = bool(resp.get("ok"))

        if not self.daemon_alive:
            self.recording = False
            self.elapsed_seconds = 0
            self.subject = ""
            self._update_visuals(
                tooltip=f"Recordo · daemon offline ({resp.get('error', '?')[:40]})",
                status_label="⚫ Daemon offline",
                toggle_label="▶  Tentar iniciar daemon",
            )
            return GLib.SOURCE_CONTINUE

        self.recording = bool(resp.get("recording"))
        if self.recording:
            self.elapsed_seconds = int(resp.get("elapsed_seconds", 0))
            self.subject = str(resp.get("subject", ""))
            self._update_visuals(
                tooltip=f"🔴 Recordo · {self.subject} · {_fmt_elapsed(self.elapsed_seconds)}",
                status_label=f"🔴 Gravando · {_fmt_elapsed(self.elapsed_seconds)}",
                toggle_label="⏹  Parar gravação",
            )
        else:
            self._update_visuals(
                tooltip="Recordo · daemon ativo · idle",
                status_label="⚫ Idle (daemon ativo)",
                toggle_label="▶  Iniciar gravação",
            )
        return GLib.SOURCE_CONTINUE

    def _update_visuals(self, *, tooltip: str, status_label: str, toggle_label: str) -> None:
        # Tooltip + ícone
        if _BACKEND == "xapp":
            self.icon.set_tooltip_text(tooltip)  # type: ignore[union-attr]
        elif _BACKEND == "ayatana":
            self.icon.set_title(tooltip)  # type: ignore[union-attr]
            # AppIndicator não tem tooltip direto; o título funciona como hint

        # Items do menu
        if "status" in self.menu_items:
            self.menu_items["status"].set_label(status_label)
        if "toggle" in self.menu_items:
            self.menu_items["toggle"].set_label(toggle_label)
        if "mark" in self.menu_items:
            self.menu_items["mark"].set_sensitive(self.recording)


def _fmt_elapsed(seconds: int) -> str:
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def run_tray() -> int:
    """Entrypoint: cria tray + roda Gtk.main(). Bloqueia até Sair."""
    if _BACKEND == "none":
        print(
            "ERRO: Tray indisponível. Instale:\n"
            "  sudo apt install gir1.2-xapp-1.0  # Cinnamon/Mint (preferido)\n"
            "  sudo apt install gir1.2-ayatanaappindicator3-0.1  # Ubuntu/GNOME",
            file=sys.stderr,
        )
        return 1
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    log.info("iniciando tray (backend=%s)", _BACKEND)
    RecordoTray()
    try:
        Gtk.main()
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(run_tray())
