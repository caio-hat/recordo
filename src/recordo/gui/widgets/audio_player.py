"""Audio player widget (C1) — Gtk.MediaFile + speed control + seek bar.

Wraps Gtk.MediaFile com controles customizados:
  - Play/Pause/Stop botões com ícones simbolic
  - Seek bar (Gtk.Scale)
  - Velocidades: 0.75 / 1.0 / 1.5 / 1.75 / 2.0 / 2.5 / 3.0
  - Position label MM:SS / MM:SS
  - Sinaliza timestamp via property notify::timestamp para sync waveform/transcript

Suporta opus, wav, mp3 nativamente via GStreamer subjacente.
"""

from __future__ import annotations

import logging
from pathlib import Path

from gi.repository import GObject, Gtk

log = logging.getLogger(__name__)


SPEEDS = [0.75, 1.0, 1.5, 1.75, 2.0, 2.5, 3.0]


class AudioPlayer(Gtk.Box):
    """Audio player widget standalone."""

    __gsignals__: dict = {  # noqa: RUF012
        # Emitido quando posição muda (a cada 100ms enquanto tocando)
        "position-changed": (GObject.SignalFlags.RUN_FIRST, None, (float,)),
        # Emitido quando user solta seek bar (após drag)
        "seek-completed": (GObject.SignalFlags.RUN_FIRST, None, (float,)),
    }

    def __init__(self, audio_path: Path):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)

        self.audio_path = audio_path
        self._seeking = False  # flag para saber se user está arrastando

        # ── MediaFile ──────────────────────────────────────────────────────
        self.media = Gtk.MediaFile.new_for_filename(str(audio_path))
        self.media.set_loop(False)
        # Sinal: posição mudou (timestamp em microssegundos GTK)
        self.media.connect("notify::timestamp", self._on_timestamp_changed)
        self.media.connect("notify::ended", self._on_ended)

        # ── UI ─────────────────────────────────────────────────────────────
        # Linha 1: Botões + Speed dropdown
        ctrl_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        ctrl_box.set_halign(Gtk.Align.CENTER)

        self.btn_play = Gtk.Button(icon_name="media-playback-start-symbolic")
        self.btn_play.add_css_class("circular")
        self.btn_play.add_css_class("suggested-action")
        self.btn_play.set_tooltip_text("Play / Pause")
        self.btn_play.connect("clicked", self._on_play_pause)
        ctrl_box.append(self.btn_play)

        self.btn_stop = Gtk.Button(icon_name="media-playback-stop-symbolic")
        self.btn_stop.add_css_class("circular")
        self.btn_stop.set_tooltip_text("Parar e voltar ao início")
        self.btn_stop.connect("clicked", self._on_stop)
        ctrl_box.append(self.btn_stop)

        # Speed dropdown
        speed_label = Gtk.Label(label="Velocidade:")
        speed_label.add_css_class("dim-label")
        ctrl_box.append(speed_label)

        self.speed_combo = Gtk.DropDown.new_from_strings([f"{s}x" for s in SPEEDS])
        self.speed_combo.set_selected(SPEEDS.index(1.0))
        self.speed_combo.set_tooltip_text("Velocidade de reprodução")
        self.speed_combo.connect("notify::selected", self._on_speed_changed)
        ctrl_box.append(self.speed_combo)

        self.append(ctrl_box)

        # Linha 2: Seek bar + position label
        seek_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)

        self.position_label = Gtk.Label(label="00:00")
        self.position_label.add_css_class("monospace")
        self.position_label.add_css_class("dim-label")
        self.position_label.set_size_request(50, -1)
        seek_box.append(self.position_label)

        self.seek_bar = Gtk.Scale(
            orientation=Gtk.Orientation.HORIZONTAL,
            adjustment=Gtk.Adjustment.new(0, 0, 1, 0.01, 0.1, 0),
        )
        self.seek_bar.set_hexpand(True)
        self.seek_bar.set_draw_value(False)
        # Capture mouse events para distinguir programmatic vs user drag
        self.seek_bar.connect("change-value", self._on_seek_change_value)
        seek_box.append(self.seek_bar)

        self.duration_label = Gtk.Label(label="00:00")
        self.duration_label.add_css_class("monospace")
        self.duration_label.add_css_class("dim-label")
        self.duration_label.set_size_request(50, -1)
        seek_box.append(self.duration_label)

        self.append(seek_box)

        # Disparar prepare da media — duration vem assincronamente
        self.media.connect("notify::prepared", self._on_prepared)

    # ── Properties helpers ─────────────────────────────────────────────────
    def get_position_seconds(self) -> float:
        """Posição atual em segundos (float)."""
        return self.media.get_timestamp() / 1_000_000.0

    def get_duration_seconds(self) -> float:
        """Duração total em segundos (0 se não preparado)."""
        if not self.media.get_prepared():
            return 0.0
        return self.media.get_duration() / 1_000_000.0

    def is_playing(self) -> bool:
        return self.media.get_playing()

    def play(self) -> None:
        self.media.play()
        self.btn_play.set_icon_name("media-playback-pause-symbolic")

    def pause(self) -> None:
        self.media.pause()
        self.btn_play.set_icon_name("media-playback-start-symbolic")

    def seek_to(self, seconds: float) -> None:
        ts = int(seconds * 1_000_000)
        self.media.seek(ts)

    # ── Signal handlers ────────────────────────────────────────────────────
    def _on_play_pause(self, _btn) -> None:
        if self.is_playing():
            self.pause()
        else:
            self.play()

    def _on_stop(self, _btn) -> None:
        self.pause()
        self.seek_to(0.0)

    def _on_speed_changed(self, *_args) -> None:
        idx = self.speed_combo.get_selected()
        if 0 <= idx < len(SPEEDS):
            self.media.set_playback_rate(SPEEDS[idx])

    def _on_seek_change_value(self, _scale, _scroll_type, value: float) -> bool:
        """User está arrastando seek bar."""
        # value está em [0, 1] (fraction da duration)
        duration = self.get_duration_seconds()
        if duration > 0:
            target_seconds = value * duration
            self.seek_to(target_seconds)
            self._update_position_label(target_seconds)
            self.emit("seek-completed", target_seconds)
        return False  # default handler

    def _on_timestamp_changed(self, *_args) -> None:
        """MediaFile mudou timestamp (chamado durante reprodução)."""
        if self._seeking:
            return
        seconds = self.get_position_seconds()
        self._update_position_label(seconds)

        # Atualiza seek bar (sem disparar change-value pelo handler)
        duration = self.get_duration_seconds()
        if duration > 0:
            with GObject.signal_handler_block(self.seek_bar, 0):
                pass  # block pode falhar; usar set sem signal
            self.seek_bar.set_value(seconds / duration)

        # Emite signal pro waveform/transcript view
        self.emit("position-changed", seconds)

    def _on_prepared(self, *_args) -> None:
        """MediaFile carregou — duration disponível."""
        duration = self.get_duration_seconds()
        self.duration_label.set_label(_fmt_time(duration))
        log.info("audio carregado: %s · %s", self.audio_path.name, _fmt_time(duration))

    def _on_ended(self, *_args) -> None:
        """MediaFile terminou."""
        if self.media.get_ended():
            self.btn_play.set_icon_name("media-playback-start-symbolic")

    def _update_position_label(self, seconds: float) -> None:
        self.position_label.set_label(_fmt_time(seconds))


def _fmt_time(seconds: float) -> str:
    """Format MM:SS or HH:MM:SS."""
    if seconds < 0:
        seconds = 0
    total = int(seconds)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"
