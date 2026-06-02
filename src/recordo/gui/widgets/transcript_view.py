"""Transcript view widget (C3) — Gtk.ListView com sync legenda + edit inline.

Mostra cada segmento do SRT como row clicável. Highlight automático do
segmento corrente conforme posição do player. Click para editar texto;
Save reescreve transcricao.txt + transcricao.srt + nota.md.

Backup .bak no primeiro edit por sessão para reverter.
"""

from __future__ import annotations

import logging
from pathlib import Path

from gi.repository import GObject, Gtk, Pango

from .waveform import parse_srt

log = logging.getLogger(__name__)


class TranscriptSegment:
    """Helper struct para um segmento do SRT/transcript."""

    def __init__(self, idx: int, start: float, end: float, text: str):
        self.idx = idx
        self.start = start
        self.end = end
        self.text = text


class TranscriptView(Gtk.ScrolledWindow):
    """Lista scrolada de segmentos com highlight de posição atual."""

    __gsignals__: dict = {  # noqa: RUF012
        "seek-requested": (GObject.SignalFlags.RUN_FIRST, None, (float,)),
        "edit-saved": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self, target_dir: Path):
        super().__init__()
        self.target_dir = target_dir
        self.segments: list[TranscriptSegment] = []
        self._segment_widgets: list[dict] = []  # cada dict: row, label, etc.
        self._current_idx: int | None = None
        self._editing_idx: int | None = None
        self._backed_up = False  # _bak feito nesta sessão?

        self.set_min_content_height(280)
        self.set_hexpand(True)
        self.set_vexpand(True)
        self.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)

        self._listbox = Gtk.ListBox()
        self._listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        self._listbox.add_css_class("boxed-list")
        self.set_child(self._listbox)

        self._load_segments()

    def _load_segments(self) -> None:
        """Carrega segmentos do .srt, fallback para transcricao.txt full text."""
        srt = self.target_dir / "transcricao.srt"
        if srt.exists():
            tuples = parse_srt(srt)
            self.segments = [TranscriptSegment(i, s, e, t) for i, (s, e, t) in enumerate(tuples)]
        else:
            # Fallback: 1 segmento com texto completo
            txt = self.target_dir / "transcricao.txt"
            if txt.exists():
                full = txt.read_text(encoding="utf-8", errors="ignore")
                self.segments = [TranscriptSegment(0, 0.0, 0.0, full)]

        # Render
        for seg in self.segments:
            self._add_segment_row(seg)

        if not self.segments:
            empty = Gtk.Label(label="(transcrição não disponível)")
            empty.add_css_class("dim-label")
            empty.set_margin_top(20)
            empty.set_margin_bottom(20)
            self._listbox.append(empty)

    def _add_segment_row(self, seg: TranscriptSegment) -> None:
        row = Gtk.ListBoxRow()
        row.set_selectable(False)
        row.idx = seg.idx  # type: ignore[attr-defined]

        hbox = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=12,
            margin_top=8,
            margin_bottom=8,
            margin_start=12,
            margin_end=12,
        )

        # Timestamp clicável
        ts_btn = Gtk.Button()
        ts_btn.add_css_class("flat")
        ts_btn.add_css_class("monospace")
        ts_btn.set_label(_fmt_time(seg.start))
        ts_btn.set_valign(Gtk.Align.START)
        ts_btn.set_size_request(70, -1)
        ts_btn.set_tooltip_text("Clique para pular pra este momento")
        ts_btn.connect("clicked", self._on_timestamp_clicked, seg.start)
        hbox.append(ts_btn)

        # Texto (label clicável que vira entry no edit)
        label = Gtk.Label(label=seg.text, xalign=0, wrap=True, hexpand=True)
        label.set_wrap_mode(Pango.WrapMode.WORD)
        label.set_selectable(False)
        label.set_margin_top(4)
        hbox.append(label)

        # Edit button
        edit_btn = Gtk.Button(icon_name="document-edit-symbolic")
        edit_btn.add_css_class("flat")
        edit_btn.set_valign(Gtk.Align.START)
        edit_btn.set_tooltip_text("Editar este segmento")
        edit_btn.connect("clicked", self._on_edit_clicked, seg.idx)
        hbox.append(edit_btn)

        row.set_child(hbox)
        self._listbox.append(row)

        self._segment_widgets.append(
            {
                "row": row,
                "hbox": hbox,
                "label": label,
                "ts_btn": ts_btn,
                "edit_btn": edit_btn,
                "segment": seg,
                "entry": None,  # criado on-demand no edit
            }
        )

    def update_position(self, seconds: float) -> None:
        """C3: highlight do segmento ativo conforme posição do player."""
        new_idx = None
        for i, seg in enumerate(self.segments):
            if seg.start <= seconds <= seg.end:
                new_idx = i
                break
            if seg.start > seconds:
                break

        if new_idx == self._current_idx:
            return

        # Remove highlight do anterior
        if self._current_idx is not None and self._current_idx < len(self._segment_widgets):
            old = self._segment_widgets[self._current_idx]
            old["row"].remove_css_class("accent")
            old["label"].remove_css_class("heading")

        # Add highlight ao novo
        if new_idx is not None and new_idx < len(self._segment_widgets):
            new = self._segment_widgets[new_idx]
            new["row"].add_css_class("accent")
            new["label"].add_css_class("heading")
            # Auto-scroll ao segmento ativo (smooth)
            adjustment = self.get_vadjustment()
            if adjustment:
                # Best-effort: scroll de modo que row fique visível
                row = new["row"]
                allocation = row.get_allocation()
                if allocation.height > 0:
                    target = allocation.y - 50
                    page_size = adjustment.get_page_size()
                    if target < adjustment.get_value() or target > adjustment.get_value() + page_size:
                        adjustment.set_value(max(0, target))

        self._current_idx = new_idx

    def _on_timestamp_clicked(self, _btn, seconds: float) -> None:
        self.emit("seek-requested", seconds)

    def _on_edit_clicked(self, _btn, idx: int) -> None:
        if self._editing_idx is not None and self._editing_idx != idx:
            # Cancela edit anterior
            self._cancel_edit(self._editing_idx)
        self._start_edit(idx)

    def _start_edit(self, idx: int) -> None:
        if idx >= len(self._segment_widgets):
            return
        widget = self._segment_widgets[idx]
        # Replace label com entry
        seg = widget["segment"]
        entry = Gtk.Entry()
        entry.set_text(seg.text)
        entry.set_hexpand(True)
        entry.connect("activate", self._on_entry_activate, idx)
        # ESC cancela
        key_ctrl = Gtk.EventControllerKey.new()
        key_ctrl.connect("key-pressed", self._on_entry_key, idx)
        entry.add_controller(key_ctrl)

        widget["hbox"].remove(widget["label"])
        widget["hbox"].insert_child_after(entry, widget["ts_btn"])
        widget["entry"] = entry
        widget["edit_btn"].set_icon_name("emblem-ok-symbolic")
        widget["edit_btn"].set_tooltip_text("Confirmar (Enter)")

        # Disconnect handler antigo, conectar save
        try:
            widget["edit_btn"].disconnect_by_func(self._on_edit_clicked)
        except Exception:
            pass
        widget["edit_btn"].connect("clicked", self._on_save_edit, idx)

        entry.grab_focus()
        self._editing_idx = idx

    def _on_entry_activate(self, _entry, idx: int) -> None:
        self._save_edit(idx)

    def _on_entry_key(self, _ctrl, keyval, _keycode, _state, idx: int) -> bool:
        from gi.repository import Gdk

        if keyval == Gdk.KEY_Escape:
            self._cancel_edit(idx)
            return True
        return False

    def _on_save_edit(self, _btn, idx: int) -> None:
        self._save_edit(idx)

    def _save_edit(self, idx: int) -> None:
        if idx >= len(self._segment_widgets):
            return
        widget = self._segment_widgets[idx]
        entry = widget.get("entry")
        if entry is None:
            return

        new_text = entry.get_text().strip()
        seg = widget["segment"]
        seg.text = new_text
        widget["label"].set_text(new_text)

        # Restore label, remove entry
        widget["hbox"].remove(entry)
        widget["hbox"].insert_child_after(widget["label"], widget["ts_btn"])
        widget["entry"] = None
        widget["edit_btn"].set_icon_name("document-edit-symbolic")
        widget["edit_btn"].set_tooltip_text("Editar este segmento")
        try:
            widget["edit_btn"].disconnect_by_func(self._on_save_edit)
        except Exception:
            pass
        widget["edit_btn"].connect("clicked", self._on_edit_clicked, idx)

        self._editing_idx = None

        # Persistir no disco
        self._persist_changes()
        self.emit("edit-saved")

    def _cancel_edit(self, idx: int) -> None:
        if idx >= len(self._segment_widgets):
            return
        widget = self._segment_widgets[idx]
        entry = widget.get("entry")
        if entry is None:
            return
        widget["hbox"].remove(entry)
        widget["hbox"].insert_child_after(widget["label"], widget["ts_btn"])
        widget["entry"] = None
        widget["edit_btn"].set_icon_name("document-edit-symbolic")
        try:
            widget["edit_btn"].disconnect_by_func(self._on_save_edit)
        except Exception:
            pass
        widget["edit_btn"].connect("clicked", self._on_edit_clicked, idx)
        self._editing_idx = None

    def _persist_changes(self) -> None:
        """Reescreve transcricao.txt, .srt e seção '## Transcrição' em nota.md."""
        # Backup .bak na primeira edição da sessão
        if not self._backed_up:
            self._do_backup()
            self._backed_up = True

        # Reescreve transcricao.txt (texto puro, joined com newlines)
        txt = self.target_dir / "transcricao.txt"
        try:
            txt.write_text(
                "\n".join(seg.text for seg in self.segments) + "\n",
                encoding="utf-8",
            )
        except OSError as e:
            log.error("falha escrever transcricao.txt: %s", e)

        # Reescreve transcricao.srt
        srt = self.target_dir / "transcricao.srt"
        srt_lines = []
        for i, seg in enumerate(self.segments, start=1):
            srt_lines.append(str(i))
            srt_lines.append(f"{_fmt_srt_time(seg.start)} --> {_fmt_srt_time(seg.end)}")
            srt_lines.append(seg.text)
            srt_lines.append("")
        try:
            srt.write_text("\n".join(srt_lines), encoding="utf-8")
        except OSError as e:
            log.error("falha escrever transcricao.srt: %s", e)

        # Atualiza seção ## Transcrição em nota.md
        nota = self.target_dir / "nota.md"
        if nota.exists():
            try:
                content = nota.read_text(encoding="utf-8")
                # Build novo bloco
                new_block_lines = []
                for seg in self.segments:
                    timestamp = _fmt_time(seg.start)
                    new_block_lines.append(f"**[{timestamp}]** {seg.text}")
                new_block = "\n\n".join(new_block_lines) + "\n"

                import re

                content = re.sub(
                    r"^## Transcrição\s*\n+([\s\S]*?)(?=^## |\Z)",
                    f"## Transcrição\n\n{new_block}\n",
                    content,
                    count=1,
                    flags=re.M,
                )
                nota.write_text(content, encoding="utf-8")
            except OSError as e:
                log.error("falha atualizar nota.md: %s", e)

        log.info("transcript edits persistidos em %s", self.target_dir.name)

    def _do_backup(self) -> None:
        """Backup de txt/srt/nota.md antes da primeira edição."""
        import shutil

        for fname in ("transcricao.txt", "transcricao.srt", "nota.md"):
            src = self.target_dir / fname
            if src.exists():
                bak = src.with_suffix(src.suffix + ".bak")
                try:
                    shutil.copy(src, bak)
                except OSError as e:
                    log.warning("backup %s falhou: %s", src, e)


def _fmt_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    total = int(seconds)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def _fmt_srt_time(seconds: float) -> str:
    """SRT format: HH:MM:SS,mmm"""
    seconds = max(0.0, seconds)
    total_ms = int(seconds * 1000)
    ms = total_ms % 1000
    total_s = total_ms // 1000
    s = total_s % 60
    m = (total_s // 60) % 60
    h = total_s // 3600
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
