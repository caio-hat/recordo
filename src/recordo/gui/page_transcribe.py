"""Page Transcribe: re-rodar transcrição numa gravação existente.

Usa o backend configurado em Settings (Configurações → Transcrição → Backend).
Não duplica configuração — só permite escolher gravação + executar.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from gi.repository import Adw, GLib, Gtk

from ..config import NOTAS_DIR, load_config
from ..pipeline import retranscribe

log = logging.getLogger(__name__)


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
        self._current_dir: Path | None = None

        # ── Header com backend/modelo atuais (read-only, vai pra Settings) ──
        self._build_header()

        # ── Lista de gravações ───────────────────────────────────────────────
        list_title = Gtk.Label(xalign=0)
        list_title.set_markup("<b>Escolha uma gravação para re-transcrever</b>")
        list_title.set_margin_top(8)
        self.append(list_title)

        scrolled = Gtk.ScrolledWindow(vexpand=True)
        scrolled.set_min_content_height(280)
        self.append(scrolled)

        self.listbox = Gtk.ListBox()
        self.listbox.add_css_class("boxed-list")
        self.listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.listbox.connect("row-selected", self._on_selected)
        scrolled.set_child(self.listbox)

        self._populate()

        # ── Botão Run + progress ─────────────────────────────────────────────
        run_box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=12,
            halign=Gtk.Align.CENTER,
            margin_top=12,
        )
        self.append(run_box)

        self.btn_run = Gtk.Button(label="✎  Re-transcrever com backend atual")
        self.btn_run.add_css_class("pill")
        self.btn_run.add_css_class("suggested-action")
        self.btn_run.set_sensitive(False)
        self.btn_run.set_tooltip_text("Roda transcrição usando o backend configurado em Configurações.")
        self.btn_run.connect("clicked", self._on_run)
        run_box.append(self.btn_run)

        self.progress = Gtk.ProgressBar()
        self.progress.set_visible(False)
        self.append(self.progress)

        self.status_label = Gtk.Label()
        self.status_label.add_css_class("dim-label")
        self.append(self.status_label)

    def _build_header(self) -> None:
        """Header com backend/modelo atuais + atalho pra Settings."""
        cfg = load_config()
        backend = cfg["transcriber"].get("backend", "whisper")
        backend_label = backend.upper()

        # Modelo específico do backend ativo
        if backend == "whisper":
            model = cfg["transcriber"]["whisper"].get("model", "?")
        elif backend == "parakeet":
            model = cfg["transcriber"]["parakeet"].get("model", "?")
        elif backend == "cohere":
            model = cfg["transcriber"]["cohere"].get("model", "?")
        else:
            model = "?"

        info_card = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=12,
            margin_bottom=4,
        )
        info_card.add_css_class("recordo-card")

        # Coluna texto
        text_col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True)

        backend_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        backend_box.append(Gtk.Image.new_from_icon_name("system-run-symbolic"))
        bk_label = Gtk.Label(xalign=0)
        bk_label.set_markup(f"<b>Backend:</b> {backend_label}")
        backend_box.append(bk_label)
        text_col.append(backend_box)

        model_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        model_box.append(Gtk.Image.new_from_icon_name("emblem-package-symbolic"))
        mod_label = Gtk.Label(xalign=0)
        mod_label.set_markup(f"<small>Modelo: <tt>{model}</tt></small>")
        mod_label.add_css_class("dim-label")
        model_box.append(mod_label)
        text_col.append(model_box)

        info_card.append(text_col)

        # Botão "Mudar configuração" → abre Settings
        btn_settings = Gtk.Button(label="⚙  Configurar")
        btn_settings.add_css_class("flat")
        btn_settings.set_valign(Gtk.Align.CENTER)
        btn_settings.set_tooltip_text("Abrir Configurações para mudar backend/modelo")
        btn_settings.connect("clicked", self._on_open_settings)
        info_card.append(btn_settings)

        self.append(info_card)

    def _on_open_settings(self, _btn) -> None:
        """Navega para a página Configurações na sidebar."""
        # window.listbox é o sidebar listbox; index 3 é "Configurações"
        try:
            row = self.window.listbox.get_row_at_index(3)
            if row:
                self.window.listbox.select_row(row)
        except Exception:
            log.warning("não foi possível navegar pra Settings")

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
            empty = Adw.ActionRow(
                title="Nenhuma gravação com audio.opus encontrada",
                subtitle=f"Esperado em {NOTAS_DIR}",
            )
            self.listbox.append(empty)
            return

        for d in dirs:
            row = Adw.ActionRow(title=d.name.replace("_", " "))
            row.path = d  # type: ignore[attr-defined]
            # Mostra duração se disponível no nota.md
            duration = self._read_duration(d)
            if duration:
                row.set_subtitle(duration)
            self.listbox.append(row)

    @staticmethod
    def _read_duration(d: Path) -> str:
        nota = d / "nota.md"
        if not nota.exists():
            return ""
        try:
            for line in nota.read_text(encoding="utf-8").splitlines()[:15]:
                if line.startswith("duration_min:"):
                    val = float(line.split(":", 1)[1].strip())
                    if val < 1:
                        return f"{int(val * 60)}s"
                    return f"{val:.1f} min"
        except Exception:
            pass
        return ""

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

        # Carrega config atualizada (caso user tenha mudado em Settings)
        cfg = load_config()
        backend = cfg["transcriber"].get("backend", "whisper")
        target = self._current_dir

        transcriber_cfg = dict(cfg["transcriber"])

        self.btn_run.set_sensitive(False)
        self.progress.set_visible(True)
        self.progress.set_pulse_step(0.05)
        self.status_label.set_text(f"Carregando backend {backend.upper()}…")

        pulse_id = GLib.timeout_add(100, self._pulse)

        def worker():
            try:
                result = retranscribe(
                    target,
                    backend=backend,
                    transcriber_cfg=transcriber_cfg,
                    language=cfg["transcriber"].get("language", "pt"),
                    summarizer_cfg=cfg.get("summarizer"),
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
            self.status_label.set_text(f"⚠ Erro: {error}")
            self.window.toast(f"⚠ Falhou: {error}")
        else:
            self.status_label.set_text(f"✓ {len(result.segments)} segmentos · backend={result.backend}")
            self.window.toast(f"✓ Re-transcrito com {result.backend}")
        return GLib.SOURCE_REMOVE
