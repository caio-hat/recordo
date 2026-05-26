"""Page Transcribe: re-rodar transcrição com outro modelo/backend."""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from gi.repository import Adw, GLib, Gtk

from ..config import NOTAS_DIR, load_config
from ..pipeline import retranscribe

log = logging.getLogger(__name__)

WHISPER_MODELS = ["tiny", "base", "small", "medium", "large-v3", "large-v3-turbo", "distil-large-v3"]
BACKENDS = ["whisper", "parakeet"]


class TranscribePage(Gtk.Box):
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
        self.cfg = load_config()
        self._current_dir: Path | None = None

        # ── Lista de gravações ───────────────────────────────────────────────
        list_title = Gtk.Label(xalign=0)
        list_title.set_markup("<b>Escolha uma gravação</b>")
        self.append(list_title)

        scrolled = Gtk.ScrolledWindow(vexpand=True)
        scrolled.set_min_content_height(200)
        self.append(scrolled)

        self.listbox = Gtk.ListBox()
        self.listbox.add_css_class("boxed-list")
        self.listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.listbox.connect("row-selected", self._on_selected)
        scrolled.set_child(self.listbox)

        self._populate()

        # ── Backend escolha ──────────────────────────────────────────────────
        options_group = Adw.PreferencesGroup(title="Opções")
        self.append(options_group)

        self.backend_row = Adw.ComboRow(title="Backend")
        self.backend_row.set_model(Gtk.StringList.new(BACKENDS))
        self.backend_row.set_selected(BACKENDS.index(self.cfg["transcriber"]["backend"]))
        options_group.add(self.backend_row)

        self.whisper_model_row = Adw.ComboRow(title="Whisper model (se backend=whisper)")
        self.whisper_model_row.set_model(Gtk.StringList.new(WHISPER_MODELS))
        cur = self.cfg["transcriber"]["whisper"]["model"]
        if cur in WHISPER_MODELS:
            self.whisper_model_row.set_selected(WHISPER_MODELS.index(cur))
        options_group.add(self.whisper_model_row)

        # ── Run + progress ───────────────────────────────────────────────────
        run_box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL, spacing=12, halign=Gtk.Align.CENTER, margin_top=12
        )
        self.append(run_box)

        self.btn_run = Gtk.Button(label="✎ Re-transcrever")
        self.btn_run.add_css_class("pill")
        self.btn_run.add_css_class("suggested-action")
        self.btn_run.set_sensitive(False)
        self.btn_run.connect("clicked", self._on_run)
        run_box.append(self.btn_run)

        self.progress = Gtk.ProgressBar()
        self.progress.set_visible(False)
        self.append(self.progress)

        self.status_label = Gtk.Label()
        self.status_label.add_css_class("dim-label")
        self.append(self.status_label)

    def _populate(self) -> None:
        while child := self.listbox.get_first_child():
            self.listbox.remove(child)

        if not NOTAS_DIR.exists():
            empty = Adw.ActionRow(title=f"{NOTAS_DIR} não existe")
            self.listbox.append(empty)
            return

        dirs = sorted(
            (d for d in NOTAS_DIR.iterdir() if d.is_dir() and (d / "audio.opus").exists()),
            key=lambda d: d.stat().st_mtime,
            reverse=True,
        )[:30]
        if not dirs:
            empty = Adw.ActionRow(title="Nenhuma gravação com audio.opus encontrada")
            self.listbox.append(empty)
            return

        for d in dirs:
            row = Adw.ActionRow(title=d.name.replace("_", " "))
            row.path = d  # type: ignore[attr-defined]
            self.listbox.append(row)

    def _on_selected(self, _lb, row) -> None:
        if not row or not hasattr(row, "path"):
            self._current_dir = None
            self.btn_run.set_sensitive(False)
            return
        self._current_dir = row.path
        self.btn_run.set_sensitive(True)

    def _on_run(self, _btn) -> None:
        if not self._current_dir:
            return
        backend = BACKENDS[self.backend_row.get_selected()]
        whisper_model = WHISPER_MODELS[self.whisper_model_row.get_selected()]
        target = self._current_dir

        transcriber_cfg = dict(self.cfg["transcriber"])
        transcriber_cfg["whisper"] = dict(transcriber_cfg["whisper"])
        transcriber_cfg["whisper"]["model"] = whisper_model

        self.btn_run.set_sensitive(False)
        self.progress.set_visible(True)
        self.progress.set_pulse_step(0.05)
        self.status_label.set_text(f"Carregando backend {backend}…")

        pulse_id = GLib.timeout_add(100, self._pulse)

        def worker():
            try:
                result = retranscribe(
                    target,
                    backend=backend,
                    transcriber_cfg=transcriber_cfg,
                    language=self.cfg["transcriber"]["language"],
                    summarizer_cfg=self.cfg.get("summarizer"),
                )
                GLib.idle_add(self._on_done, result, None, pulse_id)
            except Exception as e:
                log.exception("retranscribe falhou")
                GLib.idle_add(self._on_done, None, e, pulse_id)

        threading.Thread(target=worker, daemon=True, name="recordo-gui-retranscribe").start()

    def _pulse(self) -> bool:
        self.progress.pulse()
        return GLib.SOURCE_CONTINUE

    def _on_done(self, result, error, pulse_id) -> bool:
        GLib.source_remove(pulse_id)
        self.progress.set_visible(False)
        self.btn_run.set_sensitive(True)
        if error:
            self.status_label.set_text(f"Erro: {error}")
            self.window.toast(f"Falhou: {error}")
        else:
            self.status_label.set_text(f"✓ {len(result.segments)} segmentos · backend={result.backend}")
            self.window.toast(f"Re-transcrito com {result.backend}")
        return GLib.SOURCE_REMOVE
