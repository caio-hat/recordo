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
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import gi

# v0.2.4: defensive — em testes, Gtk 4.0 pode estar pre-carregado pelos atoms/molecules
# require_version explode com ValueError se versão diferente já loaded.
try:
    gi.require_version("Gtk", "3.0")
except ValueError:
    pass  # Gtk 4 já carregado neste process; tray import torna-se no-op

from gi.repository import GLib, Gtk

from .client import is_daemon_alive, send_to_daemon

log = logging.getLogger(__name__)

POLL_INTERVAL_MS = 2000  # status refresh
ICON_IDLE = "media-record"
ICON_RECORDING = "media-record-symbolic"
SYMBOLIC_ICON = "recordo-symbolic"  # icone instalado em hicolor/symbolic/apps/


def _query_state() -> dict:
    """Pergunta status ao daemon. Retorna dict testável."""
    if not is_daemon_alive():
        return {
            "alive": False,
            "recording": False,
            "subject": None,
            "duration_s": 0,
            "last_recordings": [],
        }
    resp = send_to_daemon("status")
    if not resp.get("ok"):
        return {
            "alive": False,
            "recording": False,
            "subject": None,
            "duration_s": 0,
            "last_recordings": [],
        }
    out: dict = {
        "alive": True,
        "recording": bool(resp.get("recording", False)),
        "subject": resp.get("subject"),
        "duration_s": int(resp.get("duration_s", 0) or resp.get("elapsed_seconds", 0) or 0),
        "last_recordings": [],
    }
    notas = Path.home() / "Notas"
    if notas.exists():
        try:
            dirs = sorted(
                (d for d in notas.iterdir() if d.is_dir()),
                key=lambda d: d.stat().st_mtime,
                reverse=True,
            )[:5]
            out["last_recordings"] = [str(d) for d in dirs]
        except OSError:
            pass
    return out


# ── Backend probe: XApp (preferido) ou Ayatana fallback ─────────────────────
_BACKEND: str = "none"
_BACKEND_ERROR: str = ""
try:
    gi.require_version("XApp", "1.0")
    from gi.repository import XApp  # type: ignore[import-not-found]

    _BACKEND = "xapp"
    log.info("tray backend: XApp 1.0 (preferido em Cinnamon/Mint/Xfce/MATE)")
except (ValueError, ImportError) as _e_xapp:
    try:
        gi.require_version("AyatanaAppIndicator3", "0.1")
        from gi.repository import AyatanaAppIndicator3 as AppIndicator  # type: ignore[import-not-found]

        _BACKEND = "ayatana"
        log.info("tray backend: AyatanaAppIndicator3 (fallback - GNOME/Ubuntu)")
    except (ValueError, ImportError) as _e_aya:
        _BACKEND_ERROR = (
            f"Nenhum backend de tray disponível.\n"
            f"  XApp: {_e_xapp}\n"
            f"  Ayatana: {_e_aya}\n"
            f"\n"
            f"Para instalar (Linux Mint/Cinnamon recomendado):\n"
            f"  sudo apt install gir1.2-xapp-1.0\n"
            f"\n"
            f"Para outros DEs:\n"
            f"  sudo apt install gir1.2-ayatanaappindicator3-0.1"
        )
        log.error("tray indisponível:\n%s", _BACKEND_ERROR)


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

        # ── Status (não-clicável) ──────────────────────────────────────────
        status_item = Gtk.MenuItem(label="⚫ Daemon offline")
        status_item.set_sensitive(False)
        self.menu.append(status_item)
        self.menu_items["status"] = status_item

        self.menu.append(Gtk.SeparatorMenuItem())

        # ── Toggle gravação (estado-aware) ─────────────────────────────────
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

        # ── T1: Submenu Gravações Recentes ─────────────────────────────────
        recent_item = Gtk.MenuItem(label="📂  Gravações recentes")
        recent_submenu = Gtk.Menu()
        recent_item.set_submenu(recent_submenu)
        self.menu.append(recent_item)
        self.menu_items["recent"] = recent_item
        self.menu_items["recent_submenu"] = recent_submenu  # type: ignore[assignment]

        # ── T1: Submenu Pipeline ───────────────────────────────────────────
        pipeline_item = Gtk.MenuItem(label="⚙  Pipeline")
        pipeline_submenu = Gtk.Menu()

        # Toggle auto-pipeline (CheckMenuItem)
        from .config import load_config

        cfg = load_config()
        auto_run = cfg.get("pipeline", {}).get("auto_run", False)
        auto_pipe_item = Gtk.CheckMenuItem(label="Auto-pipeline (transcreve ao parar)")
        auto_pipe_item.set_active(auto_run)
        auto_pipe_item.connect("toggled", self._on_toggle_auto_pipeline)
        pipeline_submenu.append(auto_pipe_item)
        self.menu_items["auto_pipeline_check"] = auto_pipe_item  # type: ignore[assignment]

        pipeline_submenu.append(Gtk.SeparatorMenuItem())

        last_transcribe_item = Gtk.MenuItem(label="✎  Transcrever última gravação")
        last_transcribe_item.connect("activate", self._on_run_last_step, "transcribe")
        pipeline_submenu.append(last_transcribe_item)

        last_summary_item = Gtk.MenuItem(label="📝  Resumir última gravação")
        last_summary_item.connect("activate", self._on_run_last_step, "summarize")
        pipeline_submenu.append(last_summary_item)

        last_tasks_item = Gtk.MenuItem(label="✅  Extrair tarefas da última")
        last_tasks_item.connect("activate", self._on_run_last_step, "tasks")
        pipeline_submenu.append(last_tasks_item)

        pipeline_submenu.append(Gtk.SeparatorMenuItem())

        unload_ollama_item = Gtk.MenuItem(label="🧹  Encerrar Ollama agora")
        unload_ollama_item.connect("activate", self._on_unload_ollama)
        pipeline_submenu.append(unload_ollama_item)

        pipeline_item.set_submenu(pipeline_submenu)
        self.menu.append(pipeline_item)

        # ── T1: Submenu Próxima gravação ───────────────────────────────────
        next_item = Gtk.MenuItem(label="🎧  Próxima gravação")
        next_submenu = Gtk.Menu()

        # Backend (radio)
        backend_item = Gtk.MenuItem(label="Backend transcrição")
        backend_submenu = Gtk.Menu()
        backend_group: list[Gtk.RadioMenuItem] = []
        current_backend = cfg.get("transcriber", {}).get("backend", "whisper")
        for bk in ["whisper", "parakeet", "cohere"]:
            item = Gtk.RadioMenuItem(label=bk.capitalize(), group=backend_group[0] if backend_group else None)
            backend_group.append(item)
            item.set_active(bk == current_backend)
            item.connect("toggled", self._on_select_backend, bk)
            backend_submenu.append(item)
        backend_item.set_submenu(backend_submenu)
        next_submenu.append(backend_item)

        # Layout (radio)
        layout_item = Gtk.MenuItem(label="Layout áudio")
        layout_submenu = Gtk.Menu()
        layout_group: list[Gtk.RadioMenuItem] = []
        current_layout = cfg.get("recording", {}).get("layout", "merge")
        for lay in ["merge", "split"]:
            label = "Estéreo (merge)" if lay == "merge" else "Mono separado (split)"
            item = Gtk.RadioMenuItem(label=label, group=layout_group[0] if layout_group else None)
            layout_group.append(item)
            item.set_active(lay == current_layout)
            item.connect("toggled", self._on_select_layout, lay)
            layout_submenu.append(item)
        layout_item.set_submenu(layout_submenu)
        next_submenu.append(layout_item)

        # Bitrate (radio)
        bitrate_item = Gtk.MenuItem(label="Bitrate Opus")
        bitrate_submenu = Gtk.Menu()
        bitrate_group: list[Gtk.RadioMenuItem] = []
        current_bitrate = cfg.get("recording", {}).get("bitrate", "32k")
        for br in ["24k", "32k", "48k", "64k", "96k", "128k"]:
            item = Gtk.RadioMenuItem(label=br, group=bitrate_group[0] if bitrate_group else None)
            bitrate_group.append(item)
            item.set_active(br == current_bitrate)
            item.connect("toggled", self._on_select_bitrate, br)
            bitrate_submenu.append(item)
        bitrate_item.set_submenu(bitrate_submenu)
        next_submenu.append(bitrate_item)

        next_item.set_submenu(next_submenu)
        self.menu.append(next_item)

        self.menu.append(Gtk.SeparatorMenuItem())

        # ── Atalhos rápidos ────────────────────────────────────────────────
        gui_item = Gtk.MenuItem(label="🪟  Abrir GUI desktop")
        gui_item.connect("activate", self._on_open_gui)
        self.menu.append(gui_item)
        self.menu_items["gui"] = gui_item

        notas_item = Gtk.MenuItem(label="📂  Abrir ~/Notas")
        notas_item.connect("activate", self._on_open_notas)
        self.menu.append(notas_item)

        settings_item = Gtk.MenuItem(label="⚙  Configurações")
        settings_item.connect("activate", self._on_open_settings)
        self.menu.append(settings_item)

        reload_item = Gtk.MenuItem(label="↻  Recarregar config")
        reload_item.connect("activate", self._on_reload_config)
        self.menu.append(reload_item)

        self.menu.append(Gtk.SeparatorMenuItem())

        # ── T2: Submenu Daemon (state-aware) ───────────────────────────────
        daemon_menu_item = Gtk.MenuItem(label="🔌  Daemon")
        daemon_submenu = Gtk.Menu()

        start_daemon_item = Gtk.MenuItem(label="▶  Iniciar daemon")
        start_daemon_item.connect("activate", self._on_start_daemon)
        daemon_submenu.append(start_daemon_item)
        self.menu_items["daemon_start"] = start_daemon_item

        restart_daemon_item = Gtk.MenuItem(label="↻  Reiniciar daemon")
        restart_daemon_item.connect("activate", self._on_restart_daemon)
        daemon_submenu.append(restart_daemon_item)
        self.menu_items["daemon_restart"] = restart_daemon_item

        quit_daemon_item = Gtk.MenuItem(label="⏻  Encerrar daemon")
        quit_daemon_item.connect("activate", self._on_quit_daemon)
        daemon_submenu.append(quit_daemon_item)
        self.menu_items["daemon_quit"] = quit_daemon_item

        daemon_menu_item.set_submenu(daemon_submenu)
        self.menu.append(daemon_menu_item)

        # ── Sair tray ─────────────────────────────────────────────────────
        quit_item = Gtk.MenuItem(label="✕  Sair (daemon continua)")
        quit_item.connect("activate", self._on_quit_tray)
        self.menu.append(quit_item)

        self.menu.show_all()

        # Popula recentes (async-ish — uma vez ao montar, depois refresh em poll)
        self._populate_recent()

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

    # ── T1: Recent recordings ─────────────────────────────────────────────
    def _populate_recent(self) -> None:
        """Lista 5 últimas gravações no submenu Gravações Recentes."""
        from .config import NOTAS_DIR
        from .pipeline import get_recording_status

        submenu = self.menu_items.get("recent_submenu")
        if submenu is None:
            return

        # Limpar items antigos
        for child in submenu.get_children():
            submenu.remove(child)

        if not NOTAS_DIR.exists():
            empty = Gtk.MenuItem(label="(nenhuma gravação)")
            empty.set_sensitive(False)
            submenu.append(empty)
            submenu.show_all()
            return

        try:
            dirs = sorted(
                (d for d in NOTAS_DIR.iterdir() if d.is_dir() and (d / "audio.opus").exists()),
                key=lambda d: d.stat().st_mtime,
                reverse=True,
            )[:5]
        except OSError:
            dirs = []

        if not dirs:
            empty = Gtk.MenuItem(label="(nenhuma gravação)")
            empty.set_sensitive(False)
            submenu.append(empty)
        else:
            for d in dirs:
                status = get_recording_status(d)
                # Status icons: ✓ ou ✗
                badges = []
                if status["has_transcript"]:
                    badges.append("📝")
                if status["has_summary"]:
                    badges.append("📋")
                if status["has_tasks"]:
                    badges.append("✅")
                badge_str = " ".join(badges) if badges else "🎙"

                # Truncar nome longo
                name = d.name.replace("_", " ")
                if len(name) > 38:
                    name = name[:35] + "..."

                label = f"{badge_str}  {name}"
                item = Gtk.MenuItem(label=label)
                item.connect("activate", self._on_open_recording, d)
                submenu.append(item)

        submenu.show_all()

    @staticmethod
    def _on_open_recording(_item: Gtk.MenuItem, target_dir) -> None:
        try:
            subprocess.Popen(
                ["xdg-open", str(target_dir)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            log.warning("xdg-open não disponível")

    # ── T1: Pipeline submenu actions ───────────────────────────────────────
    def _on_toggle_auto_pipeline(self, item: Gtk.CheckMenuItem) -> None:
        """Toggle pipeline.auto_run em config + reload daemon."""
        from .config import load_config, save_config

        new_value = item.get_active()
        cfg = load_config()
        cfg.setdefault("pipeline", {})["auto_run"] = new_value
        save_config(cfg)
        send_to_daemon("reload_config")
        log.info("auto-pipeline: %s", "ON" if new_value else "OFF")

    def _on_run_last_step(self, _item: Gtk.MenuItem, step: str) -> None:
        """Aciona run_step na última gravação (background thread)."""
        import threading

        from .config import NOTAS_DIR
        from .pipeline import run_step

        if not NOTAS_DIR.exists():
            self._notify_error("Pipeline", "~/Notas não existe")
            return

        try:
            dirs = sorted(
                (d for d in NOTAS_DIR.iterdir() if d.is_dir() and (d / "audio.opus").exists()),
                key=lambda d: d.stat().st_mtime,
                reverse=True,
            )
        except OSError:
            dirs = []

        if not dirs:
            self._notify_error("Pipeline", "nenhuma gravação encontrada")
            return

        last = dirs[0]
        step_label = {"transcribe": "Transcrição", "summarize": "Resumo", "tasks": "Tarefas"}[step]

        try:
            subprocess.run(
                ["notify-send", "-a", "Recordo", f"⏳ {step_label}", last.name],
                timeout=2,
                check=False,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

        def worker():
            try:
                result = run_step(last, step)
                msg = (
                    f"✓ {step_label}: {result.get('backend', 'OK')}"
                    if result.get("ok")
                    else f"⚠ {result.get('error', '?')}"
                )
            except Exception as e:
                msg = f"⚠ {e}"
            try:
                subprocess.run(
                    ["notify-send", "-a", "Recordo", f"Pipeline: {last.name}", msg],
                    timeout=2,
                    check=False,
                )
            except (FileNotFoundError, subprocess.TimeoutExpired):
                pass
            # Re-popula menu de recentes (badges atualizadas)
            GLib.idle_add(self._populate_recent)

        threading.Thread(target=worker, daemon=True, name=f"tray-{step}").start()

    @staticmethod
    def _on_unload_ollama(_item: Gtk.MenuItem) -> None:
        """Descarrega Ollama models imediatamente."""
        from .config import load_config
        from .summarizer.ollama import unload_ollama_model

        cfg = load_config()
        ollama_cfg = cfg.get("summarizer", {}).get("ollama", {})
        model = ollama_cfg.get("model", "gemma2:2b")
        host = ollama_cfg.get("host", "http://localhost:11434")
        ok = unload_ollama_model(model, host=host)
        try:
            subprocess.run(
                [
                    "notify-send",
                    "-a",
                    "Recordo",
                    "🧹 Ollama" if ok else "⚠ Ollama",
                    f"Modelo {model} descarregado" if ok else "Falha ao descarregar",
                ],
                timeout=2,
                check=False,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

    # ── T1: Próxima gravação (config edits) ────────────────────────────────
    def _on_select_backend(self, item: Gtk.RadioMenuItem, backend: str) -> None:
        if not item.get_active():
            return
        from .config import load_config, save_config

        cfg = load_config()
        cfg.setdefault("transcriber", {})["backend"] = backend
        save_config(cfg)
        send_to_daemon("reload_config")
        log.info("backend → %s", backend)

    def _on_select_layout(self, item: Gtk.RadioMenuItem, layout: str) -> None:
        if not item.get_active():
            return
        from .config import load_config, save_config

        cfg = load_config()
        cfg.setdefault("recording", {})["layout"] = layout
        save_config(cfg)
        send_to_daemon("reload_config")

    def _on_select_bitrate(self, item: Gtk.RadioMenuItem, bitrate: str) -> None:
        if not item.get_active():
            return
        from .config import load_config, save_config

        cfg = load_config()
        cfg.setdefault("recording", {})["bitrate"] = bitrate
        save_config(cfg)
        send_to_daemon("reload_config")

    # ── Configurações + GUI shortcuts ─────────────────────────────────────
    @staticmethod
    def _on_open_settings(_item: Gtk.MenuItem) -> None:
        """Abre GUI direto na aba Configurações via flag --gui-page."""
        try:
            subprocess.Popen(
                ["recordo-gui"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except FileNotFoundError:
            try:
                subprocess.Popen(
                    [sys.executable, "-m", "recordo.gui"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
            except OSError as e:
                log.warning("falha abrir GUI: %s", e)

    # ── T2: Daemon control ─────────────────────────────────────────────────
    def _on_start_daemon(self, _item: Gtk.MenuItem) -> None:
        """Inicia daemon via client.ensure_daemon (background)."""
        import threading

        from . import client as client_mod

        def worker():
            ok = client_mod.ensure_daemon()
            msg = "✓ Daemon iniciado" if ok else "⚠ Falha ao iniciar daemon"
            try:
                subprocess.run(
                    ["notify-send", "-a", "Recordo", "Daemon", msg],
                    timeout=2,
                    check=False,
                )
            except (FileNotFoundError, subprocess.TimeoutExpired):
                pass
            GLib.idle_add(self._refresh_status)

        threading.Thread(target=worker, daemon=True, name="tray-start-daemon").start()

    def _on_restart_daemon(self, _item: Gtk.MenuItem) -> None:
        """Encerra + reinicia daemon."""
        import threading
        import time as _time

        from . import client as client_mod

        def worker():
            send_to_daemon("quit")
            # Espera até 5s pro socket sumir
            for _ in range(20):
                if not client_mod.is_daemon_alive():
                    break
                _time.sleep(0.25)
            ok = client_mod.ensure_daemon()
            msg = "✓ Daemon reiniciado" if ok else "⚠ Restart falhou"
            try:
                subprocess.run(
                    ["notify-send", "-a", "Recordo", "Daemon", msg],
                    timeout=2,
                    check=False,
                )
            except (FileNotFoundError, subprocess.TimeoutExpired):
                pass
            GLib.idle_add(self._refresh_status)

        threading.Thread(target=worker, daemon=True, name="tray-restart-daemon").start()

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
        # Tooltip + ícone (muda conforme estado)
        icon_name = ICON_RECORDING if self.recording else SYMBOLIC_ICON
        if _BACKEND == "xapp":
            self.icon.set_tooltip_text(tooltip)  # type: ignore[union-attr]
            self.icon.set_icon_name(icon_name)  # type: ignore[union-attr]
        elif _BACKEND == "ayatana":
            self.icon.set_title(tooltip)  # type: ignore[union-attr]
            self.icon.set_icon_full(icon_name, tooltip)  # type: ignore[union-attr]

        # Items do menu
        if "status" in self.menu_items:
            self.menu_items["status"].set_label(status_label)
        if "toggle" in self.menu_items:
            self.menu_items["toggle"].set_label(toggle_label)
            # Toggle só ativa quando daemon up
            self.menu_items["toggle"].set_sensitive(self.daemon_alive)
        if "mark" in self.menu_items:
            self.menu_items["mark"].set_sensitive(self.recording)

        # T2: Daemon submenu state-aware
        if "daemon_start" in self.menu_items:
            # Iniciar disponível só quando daemon offline
            self.menu_items["daemon_start"].set_sensitive(not self.daemon_alive)
        if "daemon_restart" in self.menu_items:
            # Reiniciar disponível só quando daemon online
            self.menu_items["daemon_restart"].set_sensitive(self.daemon_alive)
        if "daemon_quit" in self.menu_items:
            # Encerrar disponível só quando daemon online
            self.menu_items["daemon_quit"].set_sensitive(self.daemon_alive)


def _fmt_elapsed(seconds: int) -> str:
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def run_tray() -> int:
    """Entrypoint: cria tray + roda Gtk.main(). Bloqueia até Sair."""
    # Logging primeiro para que erros do backend probe apareçam
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    if _BACKEND == "none":
        # Mensagem detalhada com os erros específicos
        print(_BACKEND_ERROR, file=sys.stderr)
        log.error("tray exit: backend indisponível")
        return 2  # exit 2 = backend indisponível (vs 1 generic)

    # Bug fix v0.2.1: escreve PID file p/ daemon detection
    _write_tray_pid_file()

    log.info("iniciando tray (backend=%s)", _BACKEND)
    try:
        RecordoTray()
    except Exception as e:
        log.exception("falha ao criar RecordoTray: %s", e)
        print(f"ERRO ao criar tray: {e}", file=sys.stderr)
        _remove_tray_pid_file()
        return 3

    try:
        Gtk.main()
    except KeyboardInterrupt:
        log.info("tray: SIGINT recebido")
        _remove_tray_pid_file()
        return 130
    _remove_tray_pid_file()
    log.info("tray: Gtk.main() retornou normalmente")
    return 0


def _tray_pid_file() -> Path:
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
    if runtime_dir:
        return Path(runtime_dir) / "recordo-tray.pid"
    return Path("/tmp/recordo-tray.pid")


def _write_tray_pid_file() -> None:
    try:
        _tray_pid_file().write_text(str(os.getpid()))
    except OSError:
        pass


def _remove_tray_pid_file() -> None:
    try:
        _tray_pid_file().unlink(missing_ok=True)
    except OSError:
        pass


if __name__ == "__main__":
    sys.exit(run_tray())
