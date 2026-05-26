"""TUI Textual — interface moderna conectada ao daemon via UNIX socket.

Filosofia:
  - Conecta no daemon (auto-start ephemeral via ensure_daemon).
  - Polling 1s do status; atualizações reativas pelos widgets.
  - Bindings óbvios sempre visíveis no footer: r=record, m=mark, s=stop, q=quit.
  - Painéis: Status (grande), Devices, Segments+Marks, Help/Log.
  - Mouse + teclado.

Uso:
    recordo --tui

Requer textual>=0.86. Em ambiente sem TTY (CI, SSH sem tty), cai pra modo
plain (--no-tui).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import ClassVar

from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Grid, Horizontal, Vertical, VerticalScroll
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    Footer,
    Header,
    Input,
    Label,
    Static,
)

from .client import ensure_daemon, send_to_daemon
from .config import NOTAS_DIR

log = logging.getLogger(__name__)

POLL_INTERVAL = 1.0  # status refresh
LIST_REFRESH_INTERVAL = 5.0  # lista de gravações antigas


# ── Helpers async ────────────────────────────────────────────────────────────
async def daemon_call(cmd: str, **kwargs) -> dict:
    """Wrapper async: roda send_to_daemon (bloqueante) em thread."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: send_to_daemon(cmd, **kwargs))


# ── Modal: marcar momento ────────────────────────────────────────────────────
class MarkDialog(ModalScreen[str | None]):
    """Modal: input de texto opcional pra marcar momento."""

    CSS = """
    MarkDialog {
        align: center middle;
    }
    #mark-box {
        width: 60;
        height: 10;
        border: thick $accent;
        background: $surface;
        padding: 1 2;
    }
    #mark-buttons {
        height: 3;
        align: right middle;
    }
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "cancel", "Cancelar", show=True),
        Binding("ctrl+s", "submit", "Salvar marca", show=True),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id="mark-box"):
            yield Label("📍 Marcar momento (vazio = só timestamp)")
            yield Input(placeholder="ex: decisão importante…", id="mark-input")
            with Horizontal(id="mark-buttons"):
                yield Button("Cancelar", id="btn-cancel", variant="default")
                yield Button("Marcar", id="btn-mark", variant="primary")

    @on(Button.Pressed, "#btn-cancel")
    def cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#btn-mark")
    @on(Input.Submitted)
    def submit(self) -> None:
        text = self.query_one("#mark-input", Input).value
        self.dismiss(text)

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_submit(self) -> None:
        self.submit()


# ── Painéis ──────────────────────────────────────────────────────────────────
class StatusPanel(Static):
    """Painel de status grande: indicador + tempo + assunto + segmentos."""

    DEFAULT_CSS = """
    StatusPanel {
        height: 9;
        padding: 1 2;
        border: round $accent;
        background: $surface;
    }
    StatusPanel.recording {
        border: round $error;
        background: $error 20%;
    }
    StatusPanel.idle {
        border: round $primary;
    }
    """

    status: reactive[dict] = reactive({}, layout=True)

    def render(self) -> str:
        s = self.status
        if not s:
            return "[dim]Conectando ao daemon...[/dim]"
        if not s.get("ok"):
            return (
                f"[red]⚠ Daemon offline[/red]\n"
                f"[dim]{s.get('error', '?')}[/dim]\n\n"
                "Inicie com: [b]systemctl --user start recordo[/b]"
            )
        if not s.get("recording"):
            since = s.get("since_last_stop_seconds")
            since_h = (
                f"\n[dim]Última parada: há {int(since/60)}min[/dim]"
                if since else ""
            )
            return (
                "[bold cyan]○ Idle[/bold cyan]  "
                "[dim]daemon ativo, aguardando comando[/dim]\n\n"
                "[bold]Aperte [reverse] r [/reverse] para começar a gravar[/bold]"
                f"{since_h}"
            )

        elapsed = s.get("elapsed_seconds", 0)
        h, rem = divmod(elapsed, 3600)
        m, sec = divmod(rem, 60)
        elapsed_h = (
            f"{h:02d}:{m:02d}:{sec:02d}" if h else f"{m:02d}:{sec:02d}"
        )
        auto = " [dim italic](auto)[/dim italic]" if s.get("auto_started") else ""
        return (
            f"[bold red]● GRAVANDO[/bold red]{auto}  [bold]{elapsed_h}[/bold]\n"
            f"[bold]Assunto:[/bold] {s.get('subject', '?')}\n"
            f"[dim]Sessão:[/dim] {s.get('session_id', '?')}\n"
            f"[dim]Segmentos:[/dim] {s.get('segments', 0)}  ·  "
            f"[dim]Marcas:[/dim] {s.get('marks', 0)}"
        )

    def watch_status(self, new: dict) -> None:
        self.remove_class("recording", "idle")
        if not new or not new.get("ok"):
            return
        self.add_class("recording" if new.get("recording") else "idle")


class DevicesPanel(Static):
    """Lista de fontes detectadas (mic + system)."""

    DEFAULT_CSS = """
    DevicesPanel {
        padding: 0 1;
        border: round $primary 60%;
        height: 100%;
    }
    """

    sources_data: reactive[list[dict]] = reactive([], layout=True)

    def render(self) -> str:
        if not self.sources_data:
            return "[dim]Detectando dispositivos...[/dim]"
        lines = ["[bold]Dispositivos detectados[/bold]\n"]
        mics = [s for s in self.sources_data if s["kind"] == "mic"]
        sys_ = [s for s in self.sources_data if s["kind"] == "system"]
        if mics:
            lines.append("[cyan]Microfones[/cyan]")
            for m in mics[:3]:
                state_marker = "●" if m["state"] == "RUNNING" else "○"
                lines.append(f"  {state_marker} {m['name'][:40]}")
        if sys_:
            lines.append("\n[magenta]Sistema (loopback)[/magenta]")
            for sy in sys_[:3]:
                state_marker = "●" if sy["state"] == "RUNNING" else "○"
                lines.append(f"  {state_marker} {sy['name'][:40]}")
        return "\n".join(lines)


class RecentList(Static):
    """Lista das últimas gravações em ~/Notas/."""

    DEFAULT_CSS = """
    RecentList {
        padding: 0 1;
        border: round $primary 60%;
        height: 100%;
    }
    """

    notes: reactive[list[Path]] = reactive([], layout=True)

    def render(self) -> str:
        if not NOTAS_DIR.exists():
            return f"[dim]~/Notas não existe ainda[/dim]\n[dim]({NOTAS_DIR})[/dim]"
        if not self.notes:
            return "[dim]Nenhuma gravação ainda.[/dim]"
        lines = ["[bold]Últimas gravações[/bold]\n"]
        for p in self.notes[:8]:
            mtime = datetime.fromtimestamp(p.stat().st_mtime)
            lines.append(f"  · [cyan]{mtime:%d/%m %H:%M}[/cyan]  {p.name[:35]}")
        return "\n".join(lines)


# ── App principal ────────────────────────────────────────────────────────────
class RecordoTUI(App):
    """Recordo — TUI moderna conectada ao daemon."""

    TITLE = "Recordo"
    SUB_TITLE = "gravador de reuniões fricção-zero"

    CSS = """
    Screen {
        layout: vertical;
    }
    #main-grid {
        grid-size: 2 2;
        grid-columns: 2fr 1fr;
        grid-rows: auto 1fr;
        grid-gutter: 1 1;
        padding: 1;
        height: 1fr;
    }
    #status-cell { column-span: 2; }
    #help-banner {
        height: 3;
        padding: 0 2;
        background: $boost;
        color: $text;
        border-bottom: solid $primary;
        content-align: center middle;
    }
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("r", "toggle_record", "▶ Iniciar/Parar", show=True),
        Binding("space", "toggle_record", "▶ Iniciar/Parar", show=False),
        Binding("m", "mark", "📍 Marcar", show=True),
        Binding("s", "stop", "⏹ Parar", show=True),
        Binding("R", "reload_config", "↻ Reload config", show=True),
        Binding("ctrl+r", "force_refresh", "↻ Refresh", show=False),
        Binding("?", "help", "? Ajuda", show=True),
        Binding("q", "quit", "✕ Sair", show=True),
    ]

    last_status: reactive[dict] = reactive({})

    def __init__(self, *, auto_start_daemon: bool = True):
        super().__init__()
        self.auto_start_daemon = auto_start_daemon

    # ── Layout ──────────────────────────────────────────────────────────────
    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)

        # Banner de ajuda contextual
        yield Static(
            "[bold]r[/] iniciar/parar  ·  [bold]m[/] marcar momento  ·  "
            "[bold]s[/] parar  ·  [bold]?[/] ajuda completa  ·  [bold]q[/] sair",
            id="help-banner",
        )

        with Grid(id="main-grid"):
            with Vertical(id="status-cell"):
                yield StatusPanel(id="status-panel")
            yield DevicesPanel(id="devices-panel")
            yield RecentList(id="recent-list")

        yield Footer()

    # ── Lifecycle ───────────────────────────────────────────────────────────
    async def on_mount(self) -> None:
        if self.auto_start_daemon:
            ok = await asyncio.get_event_loop().run_in_executor(
                None, ensure_daemon,
            )
            if not ok:
                self.notify(
                    "Falha ao iniciar daemon. Verifique /tmp/recordo.daemon.log",
                    severity="error",
                    timeout=10,
                )

        # Polling reativo
        self.set_interval(POLL_INTERVAL, self._refresh_status)
        self.set_interval(LIST_REFRESH_INTERVAL, self._refresh_devices)
        self.set_interval(LIST_REFRESH_INTERVAL, self._refresh_recent)
        await self._refresh_status()
        await self._refresh_devices()
        await self._refresh_recent()

    async def _refresh_status(self) -> None:
        resp = await daemon_call("status")
        self.last_status = resp
        self.query_one("#status-panel", StatusPanel).status = resp

    async def _refresh_devices(self) -> None:
        from .sources import list_sources

        sources = await asyncio.get_event_loop().run_in_executor(None, list_sources)
        data = [
            {"name": s.name, "kind": s.kind, "state": s.state, "score": s.score}
            for s in sources
        ]
        self.query_one("#devices-panel", DevicesPanel).sources_data = data

    async def _refresh_recent(self) -> None:
        if not NOTAS_DIR.exists():
            return
        notes = sorted(
            (d for d in NOTAS_DIR.iterdir() if d.is_dir() and d.name.startswith("2")),
            key=lambda d: d.stat().st_mtime,
            reverse=True,
        )[:8]
        self.query_one("#recent-list", RecentList).notes = notes

    # ── Actions ─────────────────────────────────────────────────────────────
    async def action_toggle_record(self) -> None:
        resp = await daemon_call("toggle")
        self._toast_response(resp)
        await self._refresh_status()

    async def action_stop(self) -> None:
        if not self.last_status.get("recording"):
            self.notify("Nenhuma gravação ativa.", severity="warning")
            return
        resp = await daemon_call("stop")
        self._toast_response(resp)
        await self._refresh_status()
        await self._refresh_recent()

    async def action_mark(self) -> None:
        if not self.last_status.get("recording"):
            self.notify("Nenhuma gravação ativa para marcar.", severity="warning")
            return

        def _on_dialog(text: str | None) -> None:
            if text is None:
                return
            # Mantém ref viva — RUF006: dangling task se descartado
            self._mark_task = asyncio.create_task(self._do_mark(text))

        await self.push_screen(MarkDialog(), _on_dialog)

    async def _do_mark(self, text: str) -> None:
        resp = await daemon_call("mark", text=text)
        if resp.get("ok"):
            mark = resp.get("mark", {})
            ts = mark.get("ts_seconds", 0)
            self.notify(
                f"Marca [{int(ts//60):02d}:{int(ts%60):02d}] registrada.",
                severity="information",
            )
        else:
            self._toast_response(resp)

    async def action_reload_config(self) -> None:
        resp = await daemon_call("reload_config")
        if resp.get("ok"):
            changes = resp.get("changes") or []
            msg = f"Config recarregada · {len(changes)} mudança(s)"
            if changes:
                msg += "\n" + "\n".join(f"  • {c}" for c in changes[:3])
            self.notify(msg, severity="information")
        else:
            self._toast_response(resp)

    async def action_force_refresh(self) -> None:
        await self._refresh_status()
        await self._refresh_devices()
        await self._refresh_recent()

    def action_help(self) -> None:
        self.push_screen(HelpScreen())

    # ── Helpers ─────────────────────────────────────────────────────────────
    def _toast_response(self, resp: dict) -> None:
        if resp.get("ok"):
            msg = (
                resp.get("subject")
                or resp.get("target_dir")
                or "OK"
            )
            self.notify(f"✓ {msg}", severity="information")
        else:
            self.notify(
                f"⚠ {resp.get('error', 'erro desconhecido')}",
                severity="error",
            )


# ── Tela de ajuda ────────────────────────────────────────────────────────────
class HelpScreen(ModalScreen):
    """Help completo: keybindings + descrição de features."""

    CSS = """
    HelpScreen {
        align: center middle;
    }
    #help-content {
        width: 80%;
        height: 80%;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }
    """

    BINDINGS: ClassVar[list[BindingType]] = [Binding("escape,q,?", "close", "Fechar")]

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="help-content"):
            yield Static(
                "[bold cyan]Recordo — Ajuda[/]\n\n"
                "[bold]Atalhos globais (sistema):[/]\n"
                "  Super+R         iniciar/parar gravação\n"
                "  Super+Shift+M   marcar momento\n\n"
                "[bold]Atalhos desta TUI:[/]\n"
                "  r ou Espaço     iniciar/parar gravação\n"
                "  m               marcar momento (com nota opcional)\n"
                "  s               parar (não inicia se idle)\n"
                "  R               recarregar config.toml\n"
                "  Ctrl+R          forçar refresh dos painéis\n"
                "  ?               este menu\n"
                "  q               sair (daemon segue rodando)\n\n"
                "[bold]Como funciona:[/]\n"
                "  • Esta TUI conecta no daemon via UNIX socket. Se o daemon\n"
                "    não estiver rodando, ela tenta subir via systemd ou spawn\n"
                "    detached. Você pode sair (q) e o daemon continua.\n\n"
                "  • O daemon controla 2 ffmpegs paralelos: um pro mic, outro\n"
                "    pro monitor do sistema (loopback). Salva em Opus 32k voz\n"
                "    e faz merge ao final em ~/Notas/<data>_<assunto>/.\n\n"
                "  • Transcrição é automática (faster-whisper, lazy install).\n"
                "    Pode trocar pra Parakeet em config.toml.\n\n"
                "[bold]Watchdogs ativos durante gravação:[/]\n"
                "  • Hard-cap absoluto: 4 horas\n"
                "  • Auto-stop após 10min de mic mudo\n"
                "  • Auto-cycle de segmento a cada 30min\n"
                "  • Lembrete a cada 15min ('🔴 ainda gravando')\n\n"
                "[bold]Auto-detect (opt-in):[/]\n"
                "  Liga em Settings (GUI) ou edita ~/.config/recordo/config.toml\n"
                "  com [auto_detect].enabled=true. Daemon escuta eventos do\n"
                "  PulseAudio e auto-inicia gravação quando Teams/Zoom/Meet/etc\n"
                "  começam a usar o mic por mais de 8s.\n\n"
                "[dim]Esc para fechar.[/]\n",
                markup=True,
            )

    def action_close(self) -> None:
        self.dismiss()


def run_textual_tui(*, auto_start_daemon: bool = True) -> int:
    """Entrypoint pra cli.py."""
    try:
        app = RecordoTUI(auto_start_daemon=auto_start_daemon)
        app.run()
        return 0
    except KeyboardInterrupt:
        return 130
