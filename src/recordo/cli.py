"""Entry point CLI — argparse + dispatch dos modos (daemon, client, standalone)."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table

from . import __version__
from .client import send_to_daemon
from .config import (
    DEFAULT_MAX_SEGMENT,
    DEFAULT_OUTPUT_DIR,
    SOCKET_PATH,
    setup_logging,
)
from .daemon import Daemon
from .recorder import (
    Recorder,
    SessionState,
    acquire_lock,
    find_resumable,
    install_signals,
    make_session,
    set_recorder_ref,
    write_report,
)
from .sources import AudioSource, auto_pick, list_sources
from .tui import run_plain, run_tui

log = logging.getLogger(__name__)
console = Console(stderr=True)


def _print_devices(sources: list[AudioSource]) -> None:
    table = Table(title="Fontes PulseAudio/PipeWire disponíveis", expand=True)
    table.add_column("#", style="cyan", width=3)
    table.add_column("Tipo", style="magenta", width=8)
    table.add_column("Estado", width=10)
    table.add_column("Score", width=5)
    table.add_column("Nome / Descrição")
    for i, s in enumerate(sources):
        table.add_row(str(i), s.kind, s.state, str(s.score), f"{s.name}\n[dim]{s.description}[/dim]")
    Console().print(table)


def _interactive_pick(sources: list[AudioSource]) -> tuple[str, str]:
    _print_devices(sources)
    c = Console()
    mic_idx = int(c.input("[bold]Índice do MICROFONE:[/bold] "))
    sys_idx = int(c.input("[bold]Índice do SISTEMA (monitor):[/bold] "))
    return sources[mic_idx].name, sources[sys_idx].name


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="recordo",
        description="Recordo — gravador de reuniões fricção-zero (record + recordar)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--version", action="version", version=f"recordo {__version__}")
    p.add_argument("-s", "--subject", help="Assunto da gravação (define nome da pasta)")
    p.add_argument("--list-devices", action="store_true", help="Lista fontes de áudio e sai")
    p.add_argument("--mic", help="Nome PulseAudio da fonte de microfone")
    p.add_argument("--sys", dest="sys_src", help="Nome PulseAudio do monitor de sistema")
    p.add_argument("-a", "--auto", action="store_true", help="Auto-detecta mic e sys (Bluetooth>USB>builtin)")
    p.add_argument(
        "--max-segment",
        type=int,
        default=DEFAULT_MAX_SEGMENT,
        help=f"Cap por segmento em segundos (default {DEFAULT_MAX_SEGMENT})",
    )
    p.add_argument("--bitrate", default="32k", help="Bitrate Opus (default 32k voz)")
    p.add_argument(
        "--layout",
        choices=["merge", "split"],
        default="merge",
        help="merge = mix loudnorm  /  split = sys=L mic=R",
    )
    p.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Diretório base (default {DEFAULT_OUTPUT_DIR})",
    )
    p.add_argument("--no-tui", action="store_true", help="Modo plain (sem Rich Live, comandos via ENTER)")
    p.add_argument(
        "-T", "--transcribe", action="store_true", help="Transcreve arquivo final com faster-whisper"
    )
    p.add_argument("--whisper-model", default="base", help="Modelo Whisper (tiny|base|small|medium|large-v3)")
    p.add_argument("--language", default="pt", help="Idioma para transcrição (default pt)")
    p.add_argument("--resume", action="store_true", help="Retoma sessão anterior incompleta")
    p.add_argument("-v", "--verbose", action="store_true", help="Logs verbose")

    g = p.add_argument_group("daemon mode")
    g.add_argument("--daemon", action="store_true", help="Roda como daemon (UNIX socket persistente)")
    g.add_argument(
        "--toggle", action="store_true", help="Toggle gravação via daemon (start se idle, stop se ativo)"
    )
    g.add_argument("--stop", action="store_true", help="Para gravação via daemon")
    g.add_argument("--status", action="store_true", help="Mostra status do daemon")
    g.add_argument(
        "--mark",
        metavar="TEXTO",
        nargs="?",
        const="",
        default=None,
        help="Marca momento na gravação ativa (texto opcional)",
    )
    g.add_argument("--quit-daemon", action="store_true", help="Encerra daemon graciosamente")
    return p


def _dispatch_client(args: argparse.Namespace) -> int:
    """Comandos que falam com daemon e imprimem resposta JSON."""
    if args.toggle:
        resp = send_to_daemon("toggle")
    elif args.stop:
        resp = send_to_daemon("stop")
    elif args.status:
        resp = send_to_daemon("status")
    elif args.mark is not None:
        resp = send_to_daemon("mark", text=args.mark)
    elif args.quit_daemon:
        resp = send_to_daemon("quit")
    else:
        return -1  # not a client command
    print(json.dumps(resp, ensure_ascii=False, indent=2 if args.status else None))
    return 0 if resp.get("ok") else 1


def _run_daemon(args: argparse.Namespace) -> int:
    if SOCKET_PATH.exists():
        existing = send_to_daemon("status")
        if existing.get("ok"):
            console.print(f"[red]Daemon já rodando.[/red] Socket: {SOCKET_PATH}")
            return 1
        log.info("socket órfão detectado — removendo")
        SOCKET_PATH.unlink(missing_ok=True)
    d = Daemon(
        output_dir=args.output_dir,
        bitrate=args.bitrate,
        layout=args.layout,
        max_segment=args.max_segment,
        whisper_model=args.whisper_model,
        language=args.language,
    )
    try:
        asyncio.run(d.run())
    except KeyboardInterrupt:
        pass
    return 0


def _run_standalone(args: argparse.Namespace) -> int:
    """Modo CLI interativo (sem daemon) — Rich TUI ou plain."""
    sources = list_sources()
    if args.list_devices:
        _print_devices(sources)
        return 0

    if args.resume:
        prev = find_resumable(args.output_dir)
        if not prev:
            console.print("[yellow]Nenhuma sessão para retomar.[/yellow]")
            return 1
        console.print(f"[cyan]Retomando sessão:[/cyan] {prev}")
        state = SessionState.load(prev)
    else:
        mic, sys_ = args.mic, args.sys_src
        if args.auto or (not mic or not sys_):
            am, asys = auto_pick(sources)
            mic = mic or am
            sys_ = sys_ or asys
            if not mic or not sys_:
                console.print("[yellow]Auto-detect incompleto — seleção interativa.[/yellow]")
                mic, sys_ = _interactive_pick(sources)
            else:
                console.print(f"[green]Auto:[/green] mic=[cyan]{mic}[/cyan]  sys=[cyan]{sys_}[/cyan]")
        subject = args.subject or Console().input("[bold]Assunto da gravação:[/bold] ").strip() or "Gravacao"
        state = make_session(
            subject, mic, sys_, bitrate=args.bitrate, layout=args.layout, base_dir=args.output_dir
        )
        state.save()

    acquire_lock()
    install_signals()

    rec = Recorder(state, max_segment=args.max_segment, layout=state.layout)
    set_recorder_ref(rec)

    if args.no_tui:
        run_plain(rec)
    else:
        run_tui(rec)

    final = rec.finalize()
    write_report(state, final)

    if final:
        console.print(f"\n[bold green]✓ Final:[/bold green] {final}")
    else:
        console.print("\n[yellow]Nenhum áudio válido gravado.[/yellow]")

    if args.transcribe and final:
        try:
            from .pipeline import transcribe

            transcribe(final, model_size=args.whisper_model, language=args.language)
        except Exception as e:
            log.exception("falha na transcrição: %s", e)
            console.print(f"[red]Erro na transcrição:[/red] {e}")
    return 0


def main() -> int:
    args = build_parser().parse_args()
    setup_logging(verbose=args.verbose)

    # Client commands têm prioridade (não precisam de fontes nem daemon próprio)
    rc = _dispatch_client(args)
    if rc != -1:
        return rc

    if args.daemon:
        return _run_daemon(args)
    return _run_standalone(args)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
