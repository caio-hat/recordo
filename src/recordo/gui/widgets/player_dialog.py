"""Player dialog (C1-C4) — modal Adw.Window com player + waveform + transcript.

Combina AudioPlayer + WaveformWidget + TranscriptView numa janela modal
acessível clicando em uma gravação na aba Transcrever.

Features:
  - Player com play/pause/stop/seek/velocidade (C1)
  - Waveform com peaks + posição animada + pinos de marks (C2)
  - Transcript com sync de highlight + edição inline (C3)
  - Botão "Marcar momento" durante reprodução (C4)
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from gi.repository import Adw, Gtk

from .audio_player import AudioPlayer
from .transcript_view import TranscriptView
from .waveform import WaveformMark, WaveformWidget

log = logging.getLogger(__name__)


class PlayerDialog(Adw.Window):
    """Modal dialog com player completo para uma gravação."""

    def __init__(self, parent: Gtk.Window, target_dir: Path):
        super().__init__()
        self.target_dir = target_dir
        self.audio_path = target_dir / "audio.opus"
        self.set_transient_for(parent)
        self.set_modal(True)
        self.set_default_size(900, 700)
        self.set_title(f"Player — {target_dir.name.replace('_', ' ')}")

        # Header bar
        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        toolbar.add_top_bar(header)

        self.set_content(toolbar)

        # Main vertical box
        main_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=12,
            margin_top=16,
            margin_bottom=16,
            margin_start=16,
            margin_end=16,
        )
        toolbar.set_content(main_box)

        # Title with subject
        title = Gtk.Label(xalign=0)
        subject = target_dir.name.replace("_", " ")
        title.set_markup(f"<b>{subject}</b>")
        title.add_css_class("title-2")
        main_box.append(title)

        # ── 1. Audio player ───────────────────────────────────────────────
        if not self.audio_path.exists():
            err = Gtk.Label(label=f"⚠ audio.opus não encontrado em {target_dir}")
            err.add_css_class("error")
            main_box.append(err)
            return

        self.player = AudioPlayer(self.audio_path)
        self.player.add_css_class("card")
        self.player.set_margin_top(8)
        self.player.set_margin_bottom(8)
        self.player.set_margin_start(12)
        self.player.set_margin_end(12)
        main_box.append(self.player)

        # ── 2. Waveform ────────────────────────────────────────────────────
        self.waveform = WaveformWidget(self.audio_path, duration_seconds=0.0)
        self.waveform.add_css_class("card")
        main_box.append(self.waveform)

        # Carrega marks existentes (marks.json se houver)
        self._load_marks()

        # Botão "Marcar momento" (C4)
        mark_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8, halign=Gtk.Align.CENTER)
        btn_mark = Gtk.Button(label="🚩 Marcar momento atual")
        btn_mark.add_css_class("suggested-action")
        btn_mark.set_tooltip_text("Adiciona marca no timestamp atual de reprodução")
        btn_mark.connect("clicked", self._on_add_mark)
        mark_box.append(btn_mark)
        main_box.append(mark_box)

        # ── 3. Transcript view ────────────────────────────────────────────
        transcript_label = Gtk.Label(xalign=0)
        transcript_label.set_markup("<b>Transcrição</b> <small>(clique no segmento para editar)</small>")
        transcript_label.set_margin_top(8)
        main_box.append(transcript_label)

        self.transcript = TranscriptView(target_dir)
        main_box.append(self.transcript)

        # ── Wire signals ──────────────────────────────────────────────────
        # Player → waveform position update
        self.player.connect("position-changed", self._on_player_position)
        # Player → transcript highlight
        self.player.connect("position-changed", self._on_player_position_for_transcript)
        # Waveform click → seek
        self.waveform.connect("seek-requested", self._on_seek_requested)
        self.waveform.connect("mark-clicked", self._on_seek_requested)
        # Transcript click timestamp → seek
        self.transcript.connect("seek-requested", self._on_seek_requested)
        # Transcript edited → reload waveform/marks pra refletir (no-op ainda)
        self.transcript.connect("edit-saved", lambda _w: None)

        # Set initial duration on waveform when player prepared
        self.player.media.connect("notify::prepared", self._on_player_prepared)

    def _on_player_position(self, _player, seconds: float) -> None:
        self.waveform.set_position(seconds)

    def _on_player_position_for_transcript(self, _player, seconds: float) -> None:
        self.transcript.update_position(seconds)

    def _on_seek_requested(self, _widget, seconds: float) -> None:
        self.player.seek_to(seconds)

    def _on_player_prepared(self, *_args) -> None:
        duration = self.player.get_duration_seconds()
        self.waveform.duration = duration

    def _load_marks(self) -> None:
        """Carrega marks.json do target_dir e popula waveform."""
        marks_file = self.target_dir / "marks.json"
        if not marks_file.exists():
            return
        try:
            data = json.loads(marks_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            log.warning("falha carregar marks.json: %s", e)
            return

        if not isinstance(data, list):
            return

        marks = []
        for item in data:
            if not isinstance(item, dict):
                continue
            ts = item.get("offset_seconds") or item.get("timestamp_seconds") or 0.0
            note = str(item.get("note", ""))
            try:
                marks.append(WaveformMark(timestamp_seconds=float(ts), note=note))
            except (ValueError, TypeError):
                pass
        self.waveform.set_marks(marks)

    def _on_add_mark(self, _btn) -> None:
        """C4: Adiciona marca no timestamp atual."""
        current = self.player.get_position_seconds()

        # Dialog para nota opcional
        dlg = Adw.MessageDialog.new(
            self,
            "Adicionar marca",
            f"Timestamp: {_fmt_time(current)}\n\nNota opcional para esta marca:",
        )
        # Custom child (entry para nota)
        entry = Gtk.Entry()
        entry.set_placeholder_text("ex: decisão importante…")
        entry.set_activates_default(True)
        dlg.set_extra_child(entry)

        dlg.add_response("cancel", "Cancelar")
        dlg.add_response("ok", "Adicionar")
        dlg.set_default_response("ok")
        dlg.set_close_response("cancel")
        dlg.connect("response", self._on_mark_response, current, entry)
        dlg.present()

    def _on_mark_response(self, _dlg, response: str, timestamp: float, entry: Gtk.Entry) -> None:
        if response != "ok":
            return

        note = entry.get_text().strip()

        # Append em marks.json
        marks_file = self.target_dir / "marks.json"
        existing: list[dict] = []
        if marks_file.exists():
            try:
                data = json.loads(marks_file.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    existing = data
            except (json.JSONDecodeError, OSError) as e:
                log.warning("falha ler marks.json: %s", e)

        new_mark = {
            "offset_seconds": timestamp,
            "note": note,
        }
        existing.append(new_mark)

        try:
            marks_file.write_text(
                json.dumps(existing, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError as e:
            log.error("falha escrever marks.json: %s", e)
            return

        # Atualiza waveform
        self.waveform.add_mark(WaveformMark(timestamp_seconds=timestamp, note=note))
        log.info("marca adicionada em %s: %s", _fmt_time(timestamp), note)


def _fmt_time(seconds: float) -> str:
    total = int(seconds)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"
