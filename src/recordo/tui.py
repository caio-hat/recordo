"""TUI Rich Live + KeyReader pra modo standalone CLI (sem daemon)."""

from __future__ import annotations

import select
import sys
import termios
import time
import tty
from datetime import datetime

from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .recorder import Recorder


class KeyReader:
    """Stdin em cbreak — leitura não-bloqueante."""

    def __enter__(self):
        self.fd = sys.stdin.fileno()
        self.old = termios.tcgetattr(self.fd)
        tty.setcbreak(self.fd)
        return self

    def __exit__(self, *_):
        termios.tcsetattr(self.fd, termios.TCSADRAIN, self.old)

    def poll(self) -> str | None:
        if select.select([sys.stdin], [], [], 0)[0]:
            return sys.stdin.read(1)
        return None


def render_view(rec: Recorder, status: str, total: float) -> Panel:
    st = rec.state
    head = Table.grid(expand=True)
    head.add_column()
    head.add_column(justify="right")
    head.add_row(
        Text.assemble(("Assunto: ", "bold"), st.subject, "  ", ("ID: ", "dim"), st.session_id),
        Text(f"{datetime.fromisoformat(st.started_at):%d/%m %H:%M}", style="cyan"),
    )

    info = Table.grid(padding=(0, 2))
    info.add_column(style="dim")
    info.add_column()
    info.add_row("Mic", st.mic_source)
    info.add_row("Sys", st.sys_source)
    info.add_row("Codec", f"{st.codec} @ {st.bitrate}  layout={st.layout}")
    info.add_row("Total", f"{total:0.1f}s   segmentos={len(st.segments)}")
    info.add_row("Status", Text(status, style="green" if rec.recording else "yellow"))

    segs_tbl = Table(title="Segmentos", expand=True)
    segs_tbl.add_column("#", width=4)
    segs_tbl.add_column("Início", width=12)
    segs_tbl.add_column("Dur (s)", justify="right", width=8)
    segs_tbl.add_column("Tamanho", justify="right", width=10)
    segs_tbl.add_column("Status")
    for seg in st.segments[-12:]:
        size_h = f"{seg.size_bytes / 1024:.1f} KB" if seg.size_bytes else "-"
        segs_tbl.add_row(str(seg.index), seg.started_at[-8:], f"{seg.duration:.1f}", size_h, seg.status)

    if rec.recording:
        elapsed = time.monotonic() - rec.seg_start_mono
        bar = Text(
            f"  ● gravando seg{len(st.segments):03d}  ({elapsed:0.1f}s / {rec.max_segment}s)",
            style="bold red",
        )
    else:
        bar = Text("  ○ pausado", style="dim")

    body = Group(head, "", info, "", bar, "", segs_tbl)
    return Panel(
        body,
        title="[bold]Recordo[/bold]",
        subtitle="[r] start/retomar  [p] pausar  [q] encerrar  [s] split  [m] merge",
    )


def run_tui(rec: Recorder) -> None:
    total = sum(s.duration for s in rec.state.segments)
    status = "Aguardando comando."
    console = Console()

    with (
        KeyReader() as kb,
        Live(render_view(rec, status, total), refresh_per_second=4, console=console) as live,
    ):
        running = True
        while running:
            time.sleep(0.15)
            if rec.recording:
                event = rec.watchdog_tick()
                if event == "cycled":
                    status = "Rotacionou segmento (cap atingido)."
                elif event == "died":
                    status = "ffmpeg morreu — parado."

            k = kb.poll()
            if k:
                k = k.lower()
                if k == "r":
                    if not rec.recording:
                        rec.start_segment()
                        status = f"Gravando segmento {len(rec.state.segments)}."
                    else:
                        status = "Já está gravando."
                elif k == "p" and rec.recording:
                    seg = rec.stop_segment()
                    if seg:
                        total += seg.duration
                        status = f"Pausado. Segmento {seg.index} = {seg.status}."
                elif k == "q":
                    running = False
                elif k == "s":
                    rec.layout = "split"
                    status = "Layout = split (sys=L, mic=R)."
                elif k == "m":
                    rec.layout = "merge"
                    status = "Layout = merge + loudnorm."

            total_now = total + (time.monotonic() - rec.seg_start_mono) if rec.recording else total
            live.update(render_view(rec, status, total_now))


def run_plain(rec: Recorder) -> None:
    """Modo sem TUI — comandos via stdin linha-a-linha."""
    print("Comandos: r=iniciar  p=pausar  q=encerrar  (ENTER após cada)")
    while True:
        try:
            cmd = input("> ").strip().lower()
        except EOFError:
            break
        if cmd == "r":
            rec.start_segment()
            print(f"gravando seg{len(rec.state.segments):03d}")
        elif cmd == "p":
            seg = rec.stop_segment()
            print(f"segmento {seg.index} {seg.status} dur={seg.duration:.1f}s" if seg else "nada para pausar")
        elif cmd == "q":
            break
