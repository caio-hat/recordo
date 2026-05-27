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
from typing import Any, ClassVar

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


class RenameDialog(ModalScreen[str | None]):
    """Modal: input para renomear gravação selecionada (assunto novo)."""

    CSS = """
    RenameDialog {
        align: center middle;
    }
    #rename-box {
        width: 70;
        height: 12;
        border: thick $accent;
        background: $surface;
        padding: 1 2;
    }
    #rename-buttons {
        height: 3;
        align: right middle;
    }
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "cancel", "Cancelar", show=True),
        Binding("ctrl+s", "submit", "Salvar", show=True),
    ]

    def __init__(self, current_subject: str = "") -> None:
        super().__init__()
        self._current = current_subject

    def compose(self) -> ComposeResult:
        with Vertical(id="rename-box"):
            yield Label(f"✏ Renomear: [dim]{self._current}[/dim]")
            yield Label("[dim]Novo assunto (texto humano-legível):[/dim]")
            yield Input(
                value=self._current,
                placeholder="ex: Reunião Datadog · Product Review",
                id="rename-input",
            )
            with Horizontal(id="rename-buttons"):
                yield Button("Cancelar", id="btn-rename-cancel", variant="default")
                yield Button("Renomear", id="btn-rename-ok", variant="primary")

    @on(Button.Pressed, "#btn-rename-cancel")
    def cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#btn-rename-ok")
    @on(Input.Submitted)
    def submit(self) -> None:
        text = self.query_one("#rename-input", Input).value.strip()
        self.dismiss(text or None)

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
            since_h = f"\n[dim]Última parada: há {int(since / 60)}min[/dim]" if since else ""
            return (
                "[bold cyan]○ Idle[/bold cyan]  "
                "[dim]daemon ativo, aguardando comando[/dim]\n\n"
                "[bold]Aperte [reverse] r [/reverse] para começar a gravar[/bold]"
                f"{since_h}"
            )

        elapsed = s.get("elapsed_seconds", 0)
        h, rem = divmod(elapsed, 3600)
        m, sec = divmod(rem, 60)
        elapsed_h = f"{h:02d}:{m:02d}:{sec:02d}" if h else f"{m:02d}:{sec:02d}"
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
        Binding("n", "rename_recent", "✏ Renomear última", show=True),
        Binding("c", "settings", "⚙ Settings", show=True),
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
                None,
                ensure_daemon,
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
        data = [{"name": s.name, "kind": s.kind, "state": s.state, "score": s.score} for s in sources]
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
                f"Marca [{int(ts // 60):02d}:{int(ts % 60):02d}] registrada.",
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

    def action_settings(self) -> None:
        """Abre tela de Settings TUI (forms reativos)."""
        self.push_screen(SettingsScreen())

    async def action_rename_recent(self) -> None:
        """Renomeia a gravação mais recente em ~/Notas/ via dialog."""
        import re

        # Pega a gravação mais recente do RecentList
        recent_panel = self.query_one("#recent-list", RecentList)
        if not recent_panel.notes:
            self.notify("Nenhuma gravação para renomear", severity="warning")
            return
        target = recent_panel.notes[0]

        # Subject atual = nome do dir sem prefixo de data
        m = re.match(r"^\d{4}-\d{2}-\d{2}_(.+)$", target.name)
        current = m.group(1).replace("_", " ") if m else target.name

        def _on_dialog(text: str | None) -> None:
            if not text:
                return
            self._rename_task = asyncio.create_task(self._do_rename(target, text))

        await self.push_screen(RenameDialog(current_subject=current), _on_dialog)

    async def _do_rename(self, target, new_subject: str) -> None:
        """Roda rename_recording em executor + reporta resultado."""
        from .rename import rename_recording

        loop = asyncio.get_event_loop()
        try:
            result = await loop.run_in_executor(None, lambda: rename_recording(target, new_subject))
        except Exception as e:
            self.notify(f"⚠ Erro: {e}", severity="error")
            return

        if result.ok:
            self.notify(f"✓ Renomeado: {result.new_dir.name}", severity="information")
            await self._refresh_recent()
        else:
            self.notify(f"⚠ Falhou: {result.error}", severity="error")

    # ── Helpers ─────────────────────────────────────────────────────────────
    def _toast_response(self, resp: dict) -> None:
        if resp.get("ok"):
            msg = resp.get("subject") or resp.get("target_dir") or "OK"
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
                "  n               renomear última gravação\n"
                "  c               ⚙ Settings (transcriber/LLM/API keys/Ollama remoto)\n"
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
                "  • Transcrição automática (faster-whisper, lazy install).\n"
                "    Backends: [bold]whisper[/] (local, faster-whisper),\n"
                "    [bold]parakeet[/] (NVIDIA NeMo TDT v3, 25 idiomas),\n"
                "    [bold]cohere[/] (API ou local ONNX, SOTA 5.42% WER).\n\n"
                "  • Resumo automático via LLM. Backends: [bold]ollama[/] (local,\n"
                "    suporta servidor remoto via host configurável),\n"
                "    [bold]gemini[/], [bold]openai[/], [bold]anthropic[/],\n"
                "    [bold]groq/openai_compat[/]. Cascata de fallback automática.\n\n"
                "[bold]Watchdogs ativos durante gravação:[/]\n"
                "  • Hard-cap absoluto: 4 horas\n"
                "  • Auto-stop após 10min de mic mudo\n"
                "  • Auto-cycle de segmento a cada 30min\n"
                "  • Lembrete a cada 15min ('🔴 ainda gravando')\n\n"
                "[bold]Auto-detect (opt-in):[/]\n"
                "  Liga em Settings (tecla 'c') ou edita ~/.config/recordo/config.toml\n"
                "  com [auto_detect].enabled=true. Daemon escuta eventos do\n"
                "  PulseAudio e auto-inicia gravação quando Teams/Zoom/Meet/etc\n"
                "  começam a usar o mic por mais de 8s.\n\n"
                "[bold]Comandos CLI úteis:[/]\n"
                "  recordo --tray              ícone na bandeja com ações\n"
                "  recordo --search 'query'    busca em ~/Notas/\n"
                "  recordo --rename DIR --new-subject 'Novo'\n"
                "  recordo --rerun-pipeline DIR  (recovery completo)\n"
                "  recordo --reformat-transcript DIR  (transcrição em parágrafos)\n\n"
                "[dim]Esc para fechar.[/]\n",
                markup=True,
            )

    def action_close(self) -> None:
        self.dismiss()


# ── Settings Screen ──────────────────────────────────────────────────────────
class SettingsScreen(ModalScreen):
    """Configurações editáveis: transcriber, summarizer/LLM, API keys, hosts.

    Forms organizados em seções colapsáveis. Salva config.toml + dispara
    reload_config no daemon ao confirmar.
    """

    CSS = """
    SettingsScreen {
        align: center middle;
    }
    #settings-content {
        width: 90%;
        height: 90%;
        border: thick $accent;
        background: $surface;
        padding: 1 2;
    }
    .field-row {
        margin: 1 0;
    }
    .field-label {
        color: $primary;
        text-style: bold;
    }
    .section-title {
        background: $boost;
        color: $accent;
        text-style: bold;
        padding: 0 1;
        margin-top: 1;
    }
    #settings-buttons {
        height: 3;
        align: right middle;
        margin-top: 1;
    }
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "cancel", "Cancelar", show=True),
        Binding("ctrl+s", "save", "Salvar", show=True),
    ]

    def __init__(self) -> None:
        super().__init__()
        from .config import load_config

        self.cfg = load_config()
        self._inputs: dict[str, Input] = {}

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="settings-content"):
            yield Static("⚙ [bold cyan]Settings — Recordo[/]", markup=True)
            yield Static(
                "[dim]Edite, depois Ctrl+S para salvar, Esc para cancelar.[/]\n",
                markup=True,
            )

            # ── Transcrição ──
            yield Static("✍ Transcrição", classes="section-title")
            yield from self._field(
                "transcriber.backend",
                "Backend (whisper/parakeet/cohere)",
                str(self.cfg["transcriber"].get("backend", "whisper")),
            )
            yield from self._field(
                "transcriber.language",
                "Idioma (ISO 639-1)",
                str(self.cfg["transcriber"].get("language", "pt")),
            )
            yield from self._field(
                "transcriber.whisper.model",
                "Whisper: model",
                str(self.cfg["transcriber"]["whisper"].get("model", "large-v3-turbo")),
            )
            yield from self._field(
                "transcriber.whisper.device",
                "Whisper: device (cpu/cuda/auto)",
                str(self.cfg["transcriber"]["whisper"].get("device", "cpu")),
            )
            yield from self._field(
                "transcriber.whisper.initial_prompt",
                "Whisper: initial_prompt (biasing pt-BR)",
                str(self.cfg["transcriber"]["whisper"].get("initial_prompt", ""))[:200],
            )
            yield from self._field(
                "transcriber.cohere.api_key",
                "Cohere API key (vazio = env COHERE_API_KEY)",
                str(self.cfg["transcriber"].get("cohere", {}).get("api_key", "")),
                password=True,
            )

            # ── Resumo ──
            yield Static("🧠 Resumo (LLM)", classes="section-title")
            yield from self._field(
                "summarizer.backend",
                "Backend (ollama/gemini/openai/openai_compat/anthropic/heuristic/none)",
                str(self.cfg.get("summarizer", {}).get("backend", "ollama")),
            )

            sum_cfg = self.cfg.get("summarizer", {})
            yield from self._field(
                "summarizer.ollama.model",
                "Ollama: model",
                str(sum_cfg.get("ollama", {}).get("model", "gemma2:2b")),
            )
            yield from self._field(
                "summarizer.ollama.host",
                "Ollama: host (localhost OR remoto)",
                str(sum_cfg.get("ollama", {}).get("host", "http://localhost:11434")),
            )
            yield from self._field(
                "summarizer.gemini.model",
                "Gemini: model",
                str(sum_cfg.get("gemini", {}).get("model", "gemini-2.5-flash")),
            )
            yield from self._field(
                "summarizer.gemini.api_key",
                "Gemini: API key (vazio = env GEMINI_API_KEY)",
                str(sum_cfg.get("gemini", {}).get("api_key", "")),
                password=True,
            )
            yield from self._field(
                "summarizer.openai.model",
                "OpenAI: model",
                str(sum_cfg.get("openai", {}).get("model", "gpt-4o-mini")),
            )
            yield from self._field(
                "summarizer.openai.api_key",
                "OpenAI: API key (vazio = env OPENAI_API_KEY)",
                str(sum_cfg.get("openai", {}).get("api_key", "")),
                password=True,
            )
            yield from self._field(
                "summarizer.anthropic.model",
                "Anthropic: model",
                str(sum_cfg.get("anthropic", {}).get("model", "claude-3-5-haiku-20241022")),
            )
            yield from self._field(
                "summarizer.anthropic.api_key",
                "Anthropic: API key (vazio = env ANTHROPIC_API_KEY)",
                str(sum_cfg.get("anthropic", {}).get("api_key", "")),
                password=True,
            )
            yield from self._field(
                "summarizer.openai_compat.base_url",
                "Groq/OpenAI-compat: base_url",
                str(sum_cfg.get("openai_compat", {}).get("base_url", "https://api.groq.com/openai/v1")),
            )
            yield from self._field(
                "summarizer.openai_compat.model",
                "Groq/OpenAI-compat: model",
                str(sum_cfg.get("openai_compat", {}).get("model", "llama-3.3-70b-versatile")),
            )
            yield from self._field(
                "summarizer.openai_compat.api_key",
                "Groq/OpenAI-compat: API key",
                str(sum_cfg.get("openai_compat", {}).get("api_key", "")),
                password=True,
            )

            with Horizontal(id="settings-buttons"):
                yield Button("Cancelar", id="btn-set-cancel", variant="default")
                yield Button("Salvar (Ctrl+S)", id="btn-set-save", variant="primary")

    def _field(self, key: str, label: str, value: str, *, password: bool = False):
        """Gera linha [Label \\n Input] e registra input em self._inputs[key]."""
        from textual.widgets import Input as Input_

        yield Static(f"  • {label}", classes="field-label")
        inp = Input_(value=value, password=password, id=f"f-{key.replace('.', '-')}")
        self._inputs[key] = inp
        yield inp

    @on(Button.Pressed, "#btn-set-cancel")
    def cancel(self) -> None:
        self.dismiss()

    @on(Button.Pressed, "#btn-set-save")
    def save(self) -> None:
        self.action_save()

    def action_cancel(self) -> None:
        self.dismiss()

    def action_save(self) -> None:
        from .config import save_config

        # Aplica mudanças no cfg dict
        for key, inp in self._inputs.items():
            value = inp.value
            self._set_nested(self.cfg, key, value)

        save_config(self.cfg)

        # Dispara reload_config no daemon
        try:
            from .client import send_to_daemon

            resp = send_to_daemon("reload_config")
            if resp.get("ok"):
                changes = len(resp.get("changes") or [])
                msg = f"✓ Config salva — {changes} mudança(s) no daemon"
            else:
                msg = f"✓ Config salva (daemon: {resp.get('error', '?')})"
        except Exception as e:
            msg = f"✓ Config salva (daemon offline: {e})"

        self.app.notify(msg, severity="information")
        self.dismiss()

    @staticmethod
    def _set_nested(cfg: dict, dotted_key: str, value: Any) -> None:
        """Set cfg['a']['b']['c'] = value via dotted key 'a.b.c'."""
        parts = dotted_key.split(".")
        d = cfg
        for p in parts[:-1]:
            if p not in d or not isinstance(d[p], dict):
                d[p] = {}
            d = d[p]
        # Conversão por tipo da target — int se number, bool se bool
        if isinstance(d.get(parts[-1]), bool):
            d[parts[-1]] = value.lower() in ("true", "1", "yes", "on")
        elif isinstance(d.get(parts[-1]), int):
            try:
                d[parts[-1]] = int(value)
            except (ValueError, TypeError):
                d[parts[-1]] = value
        else:
            d[parts[-1]] = value


def run_textual_tui(*, auto_start_daemon: bool = True) -> int:
    """Entrypoint pra cli.py."""
    try:
        app = RecordoTUI(auto_start_daemon=auto_start_daemon)
        app.run()
        return 0
    except KeyboardInterrupt:
        return 130
