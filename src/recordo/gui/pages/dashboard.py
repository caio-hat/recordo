# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Caio Hat
"""Dashboard — tela principal do app.

Replaces 5 abas (status/control/transcribe/models/settings) com:
  - Headerbar status badge live
  - Hero record button
  - Hardware card
  - Últimas gravações (5)
  - Atalhos para sub-pages (settings/models/logs)
"""

from __future__ import annotations

import logging
import subprocess
import threading
from collections.abc import Callable
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk

from ...config import NOTAS_DIR
from ..atoms import ActionButton, Heading, PulseDot
from ..molecules import Card, EmptyState
from ..organisms import HardwareCard, RecordingCard

log = logging.getLogger(__name__)


class DashboardPage(Adw.NavigationPage):
    """NavigationPage com layout dashboard.

    Args:
        on_open_settings: callback chamado quando user clica 'Configurações'
        on_open_models: callback chamado quando user clica 'Modelos'
        on_open_logs: callback chamado quando user clica 'Logs'
        on_open_recording: callback (Path) chamado quando user clica RecordingCard
    """

    def __init__(
        self,
        *,
        on_open_settings: Callable | None = None,
        on_open_models: Callable | None = None,
        on_open_logs: Callable | None = None,
        on_open_recording: Callable[[Path], None] | None = None,
    ):
        super().__init__(title="Recordo", tag="dashboard")
        self._on_open_settings = on_open_settings
        self._on_open_models = on_open_models
        self._on_open_logs = on_open_logs
        self._on_open_recording = on_open_recording

        toolbar = Adw.ToolbarView()
        self.set_child(toolbar)

        header = Adw.HeaderBar()
        toolbar.add_top_bar(header)

        # Status badge live no header (start)
        self._status_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self._status_dot = PulseDot(size=8)
        self._status_label = Gtk.Label(label="Verificando...")
        self._status_label.add_css_class("recordo-caption")
        self._status_box.append(self._status_dot)
        self._status_box.append(self._status_label)
        header.pack_start(self._status_box)

        # Menu hamburger
        menu_btn = Gtk.MenuButton(icon_name="open-menu-symbolic")
        menu_btn.set_tooltip_text("Mais opções")
        menu_btn.set_menu_model(self._build_menu_model())
        header.pack_end(menu_btn)

        # Scrolled content
        scrolled = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        toolbar.set_content(scrolled)

        clamp = Adw.Clamp(maximum_size=720, tightening_threshold=600)
        scrolled.set_child(clamp)

        content = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=24,
            margin_top=24,
            margin_bottom=24,
            margin_start=16,
            margin_end=16,
        )
        clamp.set_child(content)

        # Hero card
        self._hero_card = self._build_hero()
        content.append(self._hero_card)

        # Hardware card
        self._hardware_card = HardwareCard()
        content.append(self._hardware_card)

        # Recordings section
        rec_section = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        rec_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        rec_header.append(Heading("Últimas gravações", level=2))
        rec_header.append(Gtk.Box(hexpand=True))
        rec_section.append(rec_header)
        self._rec_list_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        rec_section.append(self._rec_list_box)
        content.append(rec_section)

        # Atalhos rápidos
        actions_box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=12,
            halign=Gtk.Align.CENTER,
        )
        if on_open_settings:
            actions_box.append(
                ActionButton(
                    "⚙ Configurações",
                    variant="secondary",
                    on_click=on_open_settings,
                )
            )
        if on_open_models:
            actions_box.append(
                ActionButton(
                    "⬇ Modelos",
                    variant="secondary",
                    on_click=on_open_models,
                )
            )
        if on_open_logs:
            actions_box.append(ActionButton("📋 Logs", variant="flat", on_click=on_open_logs))
        content.append(actions_box)

        # Initial loads
        self._refresh_status()
        self._refresh_recordings()

        # Periodic refresh: a cada 3s
        GLib.timeout_add_seconds(3, self._periodic_refresh)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_menu_model(self) -> Gio.MenuModel:
        m = Gio.Menu.new()
        m.append("Reiniciar daemon", "app.restart-daemon")
        m.append("Recarregar configuração", "app.reload-config")
        m.append("Sobre", "app.about")
        return m

    def _build_hero(self) -> Card:
        card = Card(variant="elevated")
        card.set_margin_top(8)
        self._record_btn = Gtk.Button()
        self._record_btn.add_css_class("recordo-hero-button")
        self._record_btn.add_css_class("suggested-action")
        self._record_btn.add_css_class("pill")
        self._record_label = Gtk.Label(label="⏺  Iniciar gravação")
        self._record_btn.set_child(self._record_label)
        self._record_btn.set_halign(Gtk.Align.FILL)
        self._record_btn.connect("clicked", self._on_toggle_recording)
        card.append(self._record_btn)
        return card

    def _on_toggle_recording(self, *_: object) -> None:
        from ...client import ensure_daemon, send_to_daemon

        def worker() -> None:
            ensure_daemon()
            resp = send_to_daemon("toggle")
            ok = bool(resp.get("ok"))
            GLib.idle_add(self._refresh_status)
            if not ok:
                err = resp.get("error", "erro desconhecido")
                GLib.idle_add(self._show_toast, f"⚠ {err}")

        threading.Thread(target=worker, daemon=True, name="recordo-toggle").start()

    def _show_toast(self, message: str) -> bool:
        log.info("toast: %s", message)
        return False

    def _periodic_refresh(self) -> bool:
        self._refresh_status()
        return True

    def _refresh_status(self) -> None:
        from ...client import is_daemon_alive, send_to_daemon

        alive = is_daemon_alive()
        if not alive:
            self._status_label.set_text("Offline")
            self._record_label.set_text("Daemon offline")
            self._record_btn.set_sensitive(False)
            return
        try:
            r = send_to_daemon("status")
            recording = bool(r.get("recording", False))
            duration = int(r.get("duration_s", 0))
        except Exception:
            log.exception("status falhou")
            recording = False
            duration = 0

        self._record_btn.set_sensitive(True)
        if recording:
            mins, secs = divmod(duration, 60)
            self._status_label.set_text(f"gravando · {mins:02d}:{secs:02d}")
            self._record_label.set_text("⏹  Parar gravação")
            self._record_btn.remove_css_class("suggested-action")
            self._record_btn.add_css_class("destructive-action")
        else:
            self._status_label.set_text("online")
            self._record_label.set_text("⏺  Iniciar gravação")
            self._record_btn.remove_css_class("destructive-action")
            self._record_btn.add_css_class("suggested-action")

    def _refresh_recordings(self) -> None:
        while self._rec_list_box.get_first_child() is not None:
            self._rec_list_box.remove(self._rec_list_box.get_first_child())

        if not NOTAS_DIR.exists():
            self._rec_list_box.append(
                EmptyState(
                    icon="folder-symbolic",
                    title="Sem gravações",
                    description=(
                        f"Pasta {NOTAS_DIR} ainda não existe. Aperte iniciar para gravar a primeira."
                    ),
                )
            )
            return

        dirs = sorted(
            (d for d in NOTAS_DIR.iterdir() if d.is_dir() and (d / "audio.opus").exists()),
            key=lambda d: d.stat().st_mtime,
            reverse=True,
        )[:5]

        if not dirs:
            self._rec_list_box.append(
                EmptyState(
                    icon="folder-symbolic",
                    title="Nenhuma gravação ainda",
                    description="Aperte iniciar para gravar a primeira reunião.",
                )
            )
            return

        for d in dirs:
            card = RecordingCard(
                d,
                on_view=self._on_open_recording,
                on_open_folder=self._on_open_folder,
            )
            self._rec_list_box.append(card)

    @staticmethod
    def _on_open_folder(path: Path) -> None:
        try:
            subprocess.Popen(
                ["xdg-open", str(path)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            log.warning("xdg-open não disponível")
