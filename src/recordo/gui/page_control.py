"""Page Control: botões start/stop/mark + lista recordings.

Calls de socket são async (GLib.Thread + idle_add) pra não travar o main loop
durante operações longas como finalize+concat (timeout até 60s).
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from gi.repository import Adw, GLib, Gtk

from ..config import NOTAS_DIR
from .async_client import call_async
from .widgets.recording_row import RecordingRow

log = logging.getLogger(__name__)


class ControlPage(Gtk.Box):
    def __init__(self, window):
        super().__init__(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=12,
            margin_top=24,
            margin_bottom=24,
            margin_start=24,
            margin_end=24,
        )
        self.window = window

        # ── Botões ───────────────────────────────────────────────────────────
        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12, halign=Gtk.Align.CENTER)
        self.append(btn_box)

        self.btn_toggle = Gtk.Button(label="● Iniciar / Parar")
        self.btn_toggle.set_tooltip_text(
            "Alterna gravação (start se idle, stop se ativa). Equivalente ao atalho Super+R."
        )
        self.btn_toggle.add_css_class("pill")
        self.btn_toggle.add_css_class("suggested-action")
        self.btn_toggle.connect("clicked", self._on_toggle)
        btn_box.append(self.btn_toggle)

        self.btn_mark = Gtk.Button(label="📍 Marcar")
        self.btn_mark.set_tooltip_text(
            "Registra timestamp + nota opcional na gravação atual. Equivalente ao atalho Super+Shift+M."
        )
        self.btn_mark.add_css_class("pill")
        self.btn_mark.connect("clicked", self._on_mark)
        btn_box.append(self.btn_mark)

        self.btn_stop = Gtk.Button(label="⏹ Parar")
        self.btn_stop.set_tooltip_text(
            "Encerra gravação ativa, faz merge dos segmentos e dispara transcrição em background."
        )
        self.btn_stop.add_css_class("pill")
        self.btn_stop.add_css_class("destructive-action")
        self.btn_stop.connect("clicked", self._on_stop)
        btn_box.append(self.btn_stop)

        # ── Lista de gravações ───────────────────────────────────────────────
        listing_title = Gtk.Label(xalign=0)
        listing_title.set_markup("<b>Últimas gravações</b>")
        listing_title.set_margin_top(12)
        self.append(listing_title)

        scrolled = Gtk.ScrolledWindow(vexpand=True)
        scrolled.set_min_content_height(300)
        self.append(scrolled)

        self.listbox = Gtk.ListBox()
        self.listbox.add_css_class("boxed-list")
        self.listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        scrolled.set_child(self.listbox)

        self._populate_recordings()
        GLib.timeout_add_seconds(15, self._refresh_recordings)

    def _on_toggle(self, _btn) -> None:
        self.btn_toggle.set_sensitive(False)
        call_async("toggle", self._on_socket_response_with_refresh)

    def _on_socket_response_with_refresh(self, resp: dict) -> None:
        self.btn_toggle.set_sensitive(True)
        self.btn_stop.set_sensitive(True)
        self.window.toast(self._fmt(resp))
        # delay 500ms pra deixar o filesystem settle e mostrar a gravação nova
        GLib.timeout_add(500, self._populate_recordings_once)

    def _on_mark(self, _btn) -> None:
        # Diálogo simples Adw pra texto opcional
        dlg = Adw.MessageDialog(
            transient_for=self.window,
            modal=True,
            heading="📍 Marcar momento",
            body="Texto opcional (vazio = só timestamp):",
        )
        entry = Gtk.Entry()
        entry.set_placeholder_text("ex: decisão importante…")
        dlg.set_extra_child(entry)
        dlg.add_response("cancel", "Cancelar")
        dlg.add_response("ok", "Marcar")
        dlg.set_default_response("ok")

        def on_response(_d, resp_id):
            if resp_id == "ok":
                call_async(
                    "mark",
                    lambda r: self.window.toast(self._fmt(r)),
                    text=entry.get_text(),
                )

        dlg.connect("response", on_response)
        dlg.present()

    def _on_stop(self, _btn) -> None:
        self.btn_stop.set_sensitive(False)
        call_async("stop", self._on_socket_response_with_refresh_stop)

    def _on_socket_response_with_refresh_stop(self, resp: dict) -> None:
        self.btn_stop.set_sensitive(True)
        self.window.toast(self._fmt(resp))
        GLib.timeout_add(1000, self._populate_recordings_once)

    @staticmethod
    def _fmt(resp: dict) -> str:
        if resp.get("ok"):
            return resp.get("subject") or resp.get("target_dir") or "OK"
        return f"erro: {resp.get('error', '?')}"

    def _populate_recordings_once(self) -> bool:
        self._populate_recordings()
        return GLib.SOURCE_REMOVE

    def _refresh_recordings(self) -> bool:
        self._populate_recordings()
        return GLib.SOURCE_CONTINUE

    def _populate_recordings(self) -> None:
        # Clear
        while child := self.listbox.get_first_child():
            self.listbox.remove(child)

        if not NOTAS_DIR.exists():
            empty = Adw.ActionRow(title="Nenhuma gravação ainda", subtitle=f"Crie em {NOTAS_DIR}")
            self.listbox.append(empty)
            return

        dirs = sorted(
            (d for d in NOTAS_DIR.iterdir() if d.is_dir() and d.name.startswith("2")),
            key=lambda d: d.stat().st_mtime,
            reverse=True,
        )[:20]

        if not dirs:
            empty = Adw.ActionRow(title="Nenhuma gravação ainda")
            self.listbox.append(empty)
            return

        for d in dirs:
            row = RecordingRow(d)
            row.connect_open(self._open_recording)
            row.connect_rename(self._on_rename_recording)
            self.listbox.append(row)

    @staticmethod
    def _open_recording(path: Path) -> None:
        try:
            subprocess.Popen(["xdg-open", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except FileNotFoundError:
            log.warning("xdg-open não disponível")

    def _on_rename_recording(self, path: Path) -> None:
        """Abre dialog para renomear a gravação selecionada."""
        # Subject atual derivado do nome do diretório (sem prefixo de data)
        import re

        m = re.match(r"^\d{4}-\d{2}-\d{2}_(.+)$", path.name)
        current = m.group(1).replace("_", " ") if m else path.name

        dlg = Adw.MessageDialog(
            transient_for=self.window,
            modal=True,
            heading="✏️ Renomear gravação",
            body=f"Novo assunto para:\n[i]{path.name}[/i]",
        )
        dlg.set_body_use_markup(True)
        entry = Gtk.Entry()
        entry.set_text(current)
        entry.set_placeholder_text("ex: Reunião Product Review · Datadog")
        entry.set_activates_default(True)
        dlg.set_extra_child(entry)
        dlg.add_response("cancel", "Cancelar")
        dlg.add_response("ok", "Renomear")
        dlg.set_default_response("ok")
        dlg.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)

        def on_response(_d, resp_id):
            if resp_id != "ok":
                return
            new_subject = entry.get_text().strip()
            if not new_subject:
                self.window.toast("Assunto vazio — operação cancelada")
                return
            self._do_rename(path, new_subject)

        dlg.connect("response", on_response)
        dlg.present()

    def _do_rename(self, path: Path, new_subject: str) -> None:
        """Roda rename em thread (não trava o main loop)."""
        import threading

        from gi.repository import GLib

        from ..rename import rename_recording

        def worker():
            try:
                result = rename_recording(path, new_subject)
                GLib.idle_add(self._on_rename_done, result)
            except Exception as e:
                log.exception("rename falhou")
                GLib.idle_add(self._on_rename_error, str(e))

        threading.Thread(target=worker, daemon=True, name="recordo-gui-rename").start()

    def _on_rename_done(self, result) -> bool:
        from gi.repository import GLib

        if result.ok:
            self.window.toast(
                f"✓ Renomeado para: {result.new_dir.name}"
                + (f" · {len(result.files_updated)} arquivos atualizados" if result.files_updated else "")
            )
            # Refresh da lista após pequeno delay
            GLib.timeout_add(300, self._populate_recordings_once)
        else:
            self.window.toast(f"⚠ Falhou: {result.error}")
        return GLib.SOURCE_REMOVE

    def _on_rename_error(self, msg: str) -> bool:
        from gi.repository import GLib

        self.window.toast(f"⚠ Erro: {msg}")
        return GLib.SOURCE_REMOVE
