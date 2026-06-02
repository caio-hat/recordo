"""Audio player widget (C1) — Gtk.MediaFile + speed control + seek bar.

Bug fix v0.2.1:
  - is_prepared() (não get_prepared, que não existe)
  - Detect GtkNoMediaFile (gstreamer plugin ausente) e oferecer fallback
  - Peaks loading agora em background thread no waveform
"""

from __future__ import annotations

import logging
from pathlib import Path

from gi.repository import GObject, Gtk

log = logging.getLogger(__name__)


SPEEDS = [0.75, 1.0, 1.5, 1.75, 2.0, 2.5, 3.0]


def _media_works(media) -> bool:
    """Detect if Gtk.MediaFile is functional or fallback GtkNoMediaFile."""
    type_name = type(media).__name__
    return type_name != "GtkNoMediaFile"


class AudioPlayer(Gtk.Box):
    """Audio player widget standalone."""

    __gsignals__: dict = {  # noqa: RUF012
        "position-changed": (GObject.SignalFlags.RUN_FIRST, None, (float,)),
        "seek-completed": (GObject.SignalFlags.RUN_FIRST, None, (float,)),
    }

    def __init__(self, audio_path: Path):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)

        self.audio_path = audio_path
        self._seeking = False
        self._media_ok = False

        # ── MediaFile ──────────────────────────────────────────────────────
        self.media = Gtk.MediaFile.new_for_filename(str(audio_path))
        self._media_ok = _media_works(self.media)

        if self._media_ok:
            self.media.set_loop(False)
            self.media.connect("notify::timestamp", self._on_timestamp_changed)
            self.media.connect("notify::ended", self._on_ended)
            self.media.connect("notify::prepared", self._on_prepared)
            self.media.connect("notify::error", self._on_media_error)

        # ── UI ─────────────────────────────────────────────────────────────
        if not self._media_ok:
            # Bug fix: GtkNoMediaFile (libgtk-4-media-gstreamer ausente)
            self._build_fallback_ui()
            return

        self._build_full_ui()

    def _build_fallback_ui(self) -> None:
        """UI quando libgtk-4-media-gstreamer não está instalado."""
        warn_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=8,
            margin_top=12,
            margin_bottom=12,
        )
        warn_box.add_css_class("card")

        warn_label = Gtk.Label(xalign=0, wrap=True)
        warn_label.set_markup(
            "<b>⚠ Reprodução indisponível</b>\n\n"
            "Falta o pacote <tt>libgtk-4-media-gstreamer</tt> que provê o backend\n"
            "de áudio do GTK4. Sem ele o player não consegue tocar arquivos.\n\n"
            "Para instalar:"
        )
        warn_label.set_margin_top(12)
        warn_label.set_margin_start(16)
        warn_label.set_margin_end(16)
        warn_box.append(warn_label)

        cmd_label = Gtk.Label(xalign=0)
        cmd_label.add_css_class("monospace")
        cmd_label.set_markup("<tt>sudo apt install libgtk-4-media-gstreamer</tt>")
        cmd_label.set_selectable(True)
        cmd_label.set_margin_start(16)
        cmd_label.set_margin_end(16)
        cmd_label.set_margin_bottom(12)
        warn_box.append(cmd_label)

        # Botão fallback: abrir no player externo
        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8, halign=Gtk.Align.CENTER)
        btn_box.set_margin_top(8)
        btn_box.set_margin_bottom(12)

        btn_external = Gtk.Button(label="🎵 Abrir no player externo")
        btn_external.add_css_class("suggested-action")
        btn_external.connect("clicked", self._on_open_external)
        btn_box.append(btn_external)
        warn_box.append(btn_box)

        self.append(warn_box)

    def _build_full_ui(self) -> None:
        """UI normal quando MediaFile funciona."""
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
        self.position_label.set_size_request(60, -1)
        seek_box.append(self.position_label)

        self.seek_bar = Gtk.Scale(
            orientation=Gtk.Orientation.HORIZONTAL,
            adjustment=Gtk.Adjustment.new(0, 0, 1, 0.01, 0.1, 0),
        )
        self.seek_bar.set_hexpand(True)
        self.seek_bar.set_draw_value(False)
        self.seek_bar.connect("change-value", self._on_seek_change_value)
        seek_box.append(self.seek_bar)

        self.duration_label = Gtk.Label(label="--:--")
        self.duration_label.add_css_class("monospace")
        self.duration_label.add_css_class("dim-label")
        self.duration_label.set_size_request(60, -1)
        seek_box.append(self.duration_label)

        self.append(seek_box)

    # ── Properties helpers (bugfix: is_prepared não get_prepared) ──────────
    def get_position_seconds(self) -> float:
        if not self._media_ok:
            return 0.0
        return self.media.get_timestamp() / 1_000_000.0

    def get_duration_seconds(self) -> float:
        """Duração total em segundos (0 se não preparado ou inválido)."""
        if not self._media_ok:
            return 0.0
        # API correta: is_prepared (Gtk4)
        if hasattr(self.media, "is_prepared") and not self.media.is_prepared():
            return 0.0
        return self.media.get_duration() / 1_000_000.0

    def is_playing(self) -> bool:
        if not self._media_ok:
            return False
        return self.media.get_playing()

    def play(self) -> None:
        if not self._media_ok:
            return
        self.media.play()
        self.btn_play.set_icon_name("media-playback-pause-symbolic")

    def pause(self) -> None:
        if not self._media_ok:
            return
        self.media.pause()
        self.btn_play.set_icon_name("media-playback-start-symbolic")

    def seek_to(self, seconds: float) -> None:
        if not self._media_ok:
            return
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
        if not self._media_ok:
            return
        idx = self.speed_combo.get_selected()
        if 0 <= idx < len(SPEEDS):
            self.media.set_playback_rate(SPEEDS[idx])

    def _on_seek_change_value(self, _scale, _scroll_type, value: float) -> bool:
        if not self._media_ok:
            return False
        duration = self.get_duration_seconds()
        if duration > 0:
            target_seconds = value * duration
            self.seek_to(target_seconds)
            self._update_position_label(target_seconds)
            self.emit("seek-completed", target_seconds)
        return False

    def _on_timestamp_changed(self, *_args) -> None:
        if not self._media_ok or self._seeking:
            return
        seconds = self.get_position_seconds()
        self._update_position_label(seconds)

        duration = self.get_duration_seconds()
        if duration > 0:
            self.seek_bar.set_value(seconds / duration)

        self.emit("position-changed", seconds)

    def _on_prepared(self, *_args) -> None:
        """MediaFile carregou — duration disponível."""
        if not self._media_ok:
            return
        duration = self.get_duration_seconds()
        if duration > 0:
            self.duration_label.set_label(_fmt_time(duration))
        log.info("audio carregado: %s · %s", self.audio_path.name, _fmt_time(duration))

    def _on_ended(self, *_args) -> None:
        if not self._media_ok:
            return
        if self.media.get_ended():
            self.btn_play.set_icon_name("media-playback-start-symbolic")

    def _on_media_error(self, *_args) -> None:
        try:
            err = self.media.get_error()
            log.warning("media error: %s", err)
        except Exception:
            pass

    def _update_position_label(self, seconds: float) -> None:
        if hasattr(self, "position_label"):
            self.position_label.set_label(_fmt_time(seconds))

    def _on_open_external(self, _btn) -> None:
        import subprocess

        try:
            subprocess.Popen(
                ["xdg-open", str(self.audio_path)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            log.warning("xdg-open não disponível")


def _fmt_time(seconds: float) -> str:
    if seconds < 0:
        seconds = 0
    total = int(seconds)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"
