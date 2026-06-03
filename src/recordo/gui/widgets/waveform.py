"""Waveform widget (C2) — Gtk.DrawingArea com peaks via cairo.

Extrai peaks via ffmpeg (RMS por bucket), cacheia em <target>/.peaks.json.
Render simples mas eficaz: barras verticais proporcionais ao peak, com
linha vertical de posição atual e pinos de marcações clicáveis.

C4: Click na waveform seek; click em pino seek no timestamp da marca.
"""

from __future__ import annotations

import json
import logging
import math
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GObject, Gtk

log = logging.getLogger(__name__)


N_BUCKETS = 600  # n de barras horizontais
PEAKS_CACHE = ".peaks.json"


@dataclass
class WaveformMark:
    """Marca para mostrar como pino na waveform."""

    timestamp_seconds: float
    note: str = ""


class WaveformWidget(Gtk.DrawingArea):
    """Waveform interativo — render peaks + posição atual + marks."""

    __gsignals__: dict = {  # noqa: RUF012
        # Emitido quando user clica em qualquer ponto do waveform
        "seek-requested": (GObject.SignalFlags.RUN_FIRST, None, (float,)),
        # Emitido quando user clica em mark específica
        "mark-clicked": (GObject.SignalFlags.RUN_FIRST, None, (float,)),
    }

    def __init__(self, audio_path: Path, duration_seconds: float = 0.0):
        super().__init__()
        self.audio_path = audio_path
        self.duration = duration_seconds
        self.peaks: list[float] = []
        self.position_seconds: float = 0.0
        self.marks: list[WaveformMark] = []
        self._loading = True

        self.set_content_height(80)
        self.set_hexpand(True)
        self.set_draw_func(self._on_draw)

        # Click handler
        click_gesture = Gtk.GestureClick.new()
        click_gesture.connect("pressed", self._on_click)
        self.add_controller(click_gesture)

        # Bug fix v0.2.1: peaks em background thread (não bloqueia abertura do modal)
        import threading

        threading.Thread(
            target=self._load_peaks_thread,
            daemon=True,
            name=f"recordo-peaks-{audio_path.stem}",
        ).start()

    def _load_peaks_thread(self) -> None:
        """Background: extract/load peaks + queue redraw via GLib.idle_add."""
        from gi.repository import GLib

        cache_file = self.audio_path.parent / PEAKS_CACHE
        peaks: list[float] = []
        cached_duration = 0.0

        # Try cache first
        if cache_file.exists():
            try:
                data = json.loads(cache_file.read_text())
                if data.get("audio") == self.audio_path.name and len(data.get("peaks", [])) == N_BUCKETS:
                    peaks = data["peaks"]
                    cached_duration = data.get("duration", 0.0)
                    log.debug("waveform: peaks carregados do cache (%s)", cache_file)
            except (json.JSONDecodeError, OSError) as e:
                log.warning("cache peaks corrompido: %s", e)

        if not peaks:
            # Extract via ffmpeg (slow path)
            peaks = _extract_peaks_ffmpeg(self.audio_path, N_BUCKETS)
            if peaks:
                # Cache
                try:
                    duration = (
                        self.duration if self.duration > 0 else _ffprobe_duration(self.audio_path) or 0.0
                    )
                    cache_file.write_text(
                        json.dumps(
                            {
                                "audio": self.audio_path.name,
                                "duration": duration,
                                "peaks": peaks,
                            }
                        )
                    )
                    cached_duration = duration
                    log.debug("waveform: peaks cacheados em %s", cache_file)
                except OSError as e:
                    log.warning("falha cache peaks: %s", e)

        # Update UI in main thread
        def _commit():
            self.peaks = peaks
            if cached_duration > 0 and self.duration <= 0:
                self.duration = cached_duration
            self._loading = False
            self.queue_draw()
            return False

        GLib.idle_add(_commit)

    def set_position(self, seconds: float) -> None:
        """Update posição atual (vinda do AudioPlayer)."""
        self.position_seconds = seconds
        self.queue_draw()

    def set_marks(self, marks: list[WaveformMark]) -> None:
        self.marks = marks
        self.queue_draw()

    def add_mark(self, mark: WaveformMark) -> None:
        self.marks.append(mark)
        self.queue_draw()

    def _on_draw(self, _area, ctx, width, height):
        """Cairo render das barras + linha de posição + pinos."""
        # Background
        ctx.set_source_rgba(0.96, 0.96, 0.96, 1.0)
        ctx.rectangle(0, 0, width, height)
        ctx.fill()

        # Loading state
        if self._loading:
            ctx.set_source_rgba(0.5, 0.5, 0.5, 1.0)
            ctx.select_font_face("Sans", 0, 0)
            ctx.set_font_size(11)
            text = "⏳ Extraindo peaks da waveform…"
            extents = ctx.text_extents(text)
            ctx.move_to((width - extents.width) / 2, height / 2)
            ctx.show_text(text)
            return

        if not self.peaks:
            # Render placeholder text
            ctx.set_source_rgba(0.5, 0.5, 0.5, 1.0)
            ctx.select_font_face("Sans", 0, 0)
            ctx.set_font_size(11)
            text = "Waveform indisponível (ffmpeg não pôde extrair peaks)"
            extents = ctx.text_extents(text)
            ctx.move_to((width - extents.width) / 2, height / 2)
            ctx.show_text(text)
            return

        n = len(self.peaks)
        bar_w = width / n
        mid_y = height / 2

        # Bars
        ctx.set_source_rgba(0.3, 0.5, 0.9, 0.9)  # accent blue
        for i, peak in enumerate(self.peaks):
            # peak normalized 0..1
            bar_h = peak * (height * 0.85)
            x = i * bar_w
            ctx.rectangle(x, mid_y - bar_h / 2, max(bar_w - 0.5, 0.5), bar_h)
        ctx.fill()

        # Position line (vertical red)
        if self.duration > 0:
            pos_x = (self.position_seconds / self.duration) * width
            ctx.set_source_rgba(0.9, 0.2, 0.2, 0.9)
            ctx.set_line_width(2)
            ctx.move_to(pos_x, 0)
            ctx.line_to(pos_x, height)
            ctx.stroke()

        # Marks (pinos amarelos com triangle no topo)
        ctx.set_source_rgba(0.95, 0.7, 0.1, 0.95)  # amber
        for mark in self.marks:
            if self.duration <= 0:
                continue
            mark_x = (mark.timestamp_seconds / self.duration) * width
            # Triângulo no topo
            ctx.move_to(mark_x - 5, 0)
            ctx.line_to(mark_x + 5, 0)
            ctx.line_to(mark_x, 10)
            ctx.close_path()
            ctx.fill()
            # Linha vertical
            ctx.set_line_width(1)
            ctx.move_to(mark_x, 0)
            ctx.line_to(mark_x, height)
            ctx.stroke()

    def _on_click(self, _gesture, _n_press, x: float, y: float) -> None:
        """Clique no waveform → seek_requested. Se em pino → mark_clicked."""
        width = self.get_width()
        if width <= 0 or self.duration <= 0:
            return

        # Detect clique em pino (top 10px com tolerance ±8px horizontal)
        if y < 12:
            for mark in self.marks:
                mark_x = (mark.timestamp_seconds / self.duration) * width
                if abs(x - mark_x) <= 8:
                    self.emit("mark-clicked", mark.timestamp_seconds)
                    return

        # Caso contrário, seek normal
        target = (x / width) * self.duration
        self.emit("seek-requested", target)


def _extract_peaks_ffmpeg(audio_path: Path, n_buckets: int) -> list[float]:
    """Extrai n peaks RMS via ffmpeg + astats. Returns lista normalizada 0..1."""
    if not _has_ffmpeg():
        return []

    # Strategy: ffmpeg lê audio em PCM s16le mono, depois calculamos RMS por chunk.
    try:
        # Step 1: Determinar duração
        duration = _ffprobe_duration(audio_path)
        if duration is None or duration <= 0:
            return []

        # Step 2: ffmpeg dump raw PCM s16 mono 8kHz (suficiente pro waveform)
        cmd = [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(audio_path),
            "-ac",
            "1",
            "-ar",
            "8000",
            "-f",
            "s16le",
            "-",
        ]
        proc = subprocess.run(
            cmd,
            capture_output=True,
            timeout=120,
        )
        if proc.returncode != 0:
            log.warning("ffmpeg PCM dump falhou: %s", proc.stderr[:200])
            return []

        raw = proc.stdout
        if not raw:
            return []

        # Calcular peak RMS por bucket
        import struct

        n_samples = len(raw) // 2
        if n_samples == 0:
            return []

        samples_per_bucket = max(1, n_samples // n_buckets)
        peaks = []

        for i in range(n_buckets):
            start = i * samples_per_bucket * 2
            end = min(start + samples_per_bucket * 2, len(raw))
            chunk = raw[start:end]
            n = len(chunk) // 2
            if n == 0:
                peaks.append(0.0)
                continue
            samples = struct.unpack(f"<{n}h", chunk)
            # RMS
            sq_sum = sum(s * s for s in samples)
            rms = math.sqrt(sq_sum / n) / 32768.0
            # Compress range with sqrt para visibilidade
            peaks.append(min(1.0, math.sqrt(rms * 2)))

        return peaks
    except (subprocess.TimeoutExpired, OSError) as e:
        log.warning("falha extrair peaks: %s", e)
        return []


def _has_ffmpeg() -> bool:
    import shutil

    return shutil.which("ffmpeg") is not None


def _ffprobe_duration(audio_path: Path) -> float | None:
    if not _has_ffmpeg():
        return None
    try:
        r = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=nw=1:nk=1",
                str(audio_path),
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if r.returncode != 0:
            return None
        return float(r.stdout.strip())
    except (subprocess.TimeoutExpired, ValueError, OSError):
        return None


def parse_srt(srt_path: Path) -> list[tuple[float, float, str]]:
    """Parse SRT file → lista de (start_s, end_s, text). Helper para C3."""
    if not srt_path.exists():
        return []

    content = srt_path.read_text(encoding="utf-8", errors="ignore")
    # SRT block format:
    # 1
    # 00:00:00,500 --> 00:00:02,300
    # texto
    # (blank)
    pattern = re.compile(
        r"\d+\s*\n"
        r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*\n"
        r"(.*?)(?=\n\n|\Z)",
        re.DOTALL,
    )

    segments: list[tuple[float, float, str]] = []
    for m in pattern.finditer(content):
        h1, m1, s1, ms1, h2, m2, s2, ms2, text = m.groups()
        start = int(h1) * 3600 + int(m1) * 60 + int(s1) + int(ms1) / 1000
        end = int(h2) * 3600 + int(m2) * 60 + int(s2) + int(ms2) / 1000
        segments.append((start, end, text.strip()))
    return segments
