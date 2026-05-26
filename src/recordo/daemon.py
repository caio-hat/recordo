"""Daemon asyncio: socket UNIX + watchdogs + auto-detect."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path

from .config import (
    HARD_CAP_SECONDS,
    REMINDER_INTERVAL,
    SILENCE_CHECK_INTERVAL,
    SILENCE_MAX_SECONDS,
    SILENCE_THRESHOLD_DB,
    SOCKET_PATH,
    load_auto_detect_config,
    load_config,
)
from .notify import notify
from .pipeline import post_pipeline
from .recorder import Mark, Recorder, make_session, set_recorder_ref, write_report
from .sources import auto_pick, detect_active_call, list_sources, measure_mic_db
from .subject import detect_subject

log = logging.getLogger(__name__)


class Daemon:
    """Loop principal do daemon, dispatcher de comandos via JSON-lines."""

    def __init__(
        self,
        *,
        output_dir: Path | None = None,
        bitrate: str | None = None,
        layout: str | None = None,
        max_segment: int | None = None,
        whisper_model: str | None = None,
        language: str | None = None,
        config: dict | None = None,
    ):
        # Aceita config dict completo OU args legacy (CLI sobrescreve TOML)
        self.config: dict = config or load_config()
        self.output_dir = output_dir or Path(self.config["general"]["output_dir"]).expanduser()
        self.bitrate = bitrate or self.config["recording"]["bitrate"]
        self.layout = layout or self.config["recording"]["layout"]
        self.max_segment = max_segment or self.config["recording"]["max_segment"]
        self.language = language or self.config["transcriber"]["language"]
        # whisper_model é legacy: hoje a escolha vem de config["transcriber"]["backend"]
        self.whisper_model = whisper_model or self.config["transcriber"]["whisper"]["model"]

        self.state = None  # type: ignore[var-annotated]
        self.recorder: Recorder | None = None
        self.session_start_mono: float = 0.0
        self.marks: list[Mark] = []
        self.last_stop_mono: float = 0.0
        self.silence_streak: float = 0.0
        self._tasks: list[asyncio.Task] = []
        self._reminder_last_mono: float = 0.0
        self._auto_detect_first_seen: dict[str, float] = {}

        # Executor dedicado pra trabalho pesado (post_pipeline, measure_mic_db).
        # 2 workers: 1 pode estar rodando finalize+concat enquanto o próximo
        # toggle já começa nova sessão, sem fila no executor default do asyncio.
        self._pipeline_executor = ThreadPoolExecutor(
            max_workers=2,
            thread_name_prefix="recordo-pipeline",
        )

    # ── lifecycle ──────────────────────────────────────────────────────────
    async def run(self) -> None:
        SOCKET_PATH.parent.mkdir(parents=True, exist_ok=True)
        if SOCKET_PATH.exists():
            SOCKET_PATH.unlink()

        server = await asyncio.start_unix_server(self._handle_client, path=str(SOCKET_PATH))
        os.chmod(SOCKET_PATH, 0o600)
        log.info("daemon escutando em %s (pid=%d)", SOCKET_PATH, os.getpid())
        notify("Recordo iniciado", "Daemon ativo · Super+R para gravar", icon="media-record", transient=True)

        self._tasks.append(asyncio.create_task(self._watchdog_loop(), name="watchdog"))
        self._tasks.append(asyncio.create_task(self._auto_detect_loop(), name="auto-detect"))

        loop = asyncio.get_event_loop()
        stop_event = asyncio.Event()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop_event.set)

        try:
            async with server:
                await stop_event.wait()
        finally:
            log.info("daemon encerrando")
            await self._shutdown()

    async def _shutdown(self) -> None:
        for t in self._tasks:
            t.cancel()
        if self.recorder and self.recorder.recording:
            await self._cmd_stop({})
        try:
            SOCKET_PATH.unlink()
        except FileNotFoundError:
            pass
        # Aguarda jobs pendentes (transcrição) sem bloquear forever.
        # daemon faz shutdown gracioso; jobs >timeout serão cancelados.
        self._pipeline_executor.shutdown(wait=False, cancel_futures=False)
        notify("Recordo encerrado", "Daemon parado.", icon="media-playback-stop", transient=True)

    # ── socket handler ─────────────────────────────────────────────────────
    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            raw = await asyncio.wait_for(reader.readline(), timeout=5)
            if not raw:
                return
            try:
                req = json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError as e:
                writer.write((json.dumps({"ok": False, "error": f"JSON inválido: {e}"}) + "\n").encode())
                await writer.drain()
                return

            cmd = req.get("cmd", "")
            handlers = {
                "toggle": self._cmd_toggle,
                "start": self._cmd_start,
                "stop": self._cmd_stop,
                "mark": self._cmd_mark,
                "status": self._cmd_status,
                "quit": self._cmd_quit,
                "reload_config": self._cmd_reload_config,
            }
            handler = handlers.get(cmd)
            if not handler:
                resp = {"ok": False, "error": f"comando desconhecido: {cmd}"}
            else:
                try:
                    resp = await handler(req)
                except Exception as e:
                    log.exception("erro em comando %s", cmd)
                    resp = {"ok": False, "error": str(e)}

            writer.write((json.dumps(resp, ensure_ascii=False, default=str) + "\n").encode())
            await writer.drain()
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    # ── comandos ───────────────────────────────────────────────────────────
    async def _cmd_toggle(self, req: dict) -> dict:
        if self.recorder and self.recorder.recording:
            return await self._cmd_stop(req)
        return await self._cmd_start(req)

    async def _cmd_start(self, req: dict) -> dict:
        if self.recorder and self.recorder.recording:
            return {"ok": False, "error": "já gravando", "session_id": self.state.session_id}

        subject = req.get("subject") or detect_subject()
        auto_started = bool(req.get("auto", False))

        sources = list_sources()
        mic, sys_ = auto_pick(sources)
        if not mic or not sys_:
            return {"ok": False, "error": "fontes mic/sys não detectadas"}

        state = make_session(
            subject, mic, sys_, bitrate=self.bitrate, layout=self.layout, base_dir=self.output_dir
        )
        state.auto_started = auto_started
        state.save()

        rec = Recorder(state, max_segment=self.max_segment, layout=self.layout)
        set_recorder_ref(rec)
        rec.start_segment()

        self.state = state
        self.recorder = rec
        self.session_start_mono = time.monotonic()
        self.marks = []
        self._reminder_last_mono = self.session_start_mono
        self.silence_streak = 0.0

        title = "🎙️ Auto-gravando" if auto_started else "🔴 Gravando"
        notify(title, f"{subject}\nSuper+R para parar")
        log.info("start session=%s subject=%s auto=%s", state.session_id, subject, auto_started)
        return {"ok": True, "session_id": state.session_id, "subject": subject}

    async def _cmd_stop(self, req: dict) -> dict:
        if not self.recorder or not self.recorder.recording:
            return {"ok": False, "error": "não há gravação ativa"}

        state = self.state
        rec = self.recorder
        rec.stop_segment()
        final = rec.finalize()
        write_report(state, final)

        target = None
        if final:
            loop = asyncio.get_event_loop()
            target = await loop.run_in_executor(
                self._pipeline_executor,
                lambda: post_pipeline(
                    state,
                    final,
                    self.marks,
                    config=self.config,
                    language=self.language,
                ),
            )

        if target:
            notify(
                "⏹ Salvo · transcrevendo…",
                f"~/Notas/{target.name}/",
                icon="media-playback-stop",
                transient=True,
            )
        else:
            notify("⏹ Encerrado", "Nenhum áudio gerado.", icon="dialog-warning", urgency="critical")

        self.last_stop_mono = time.monotonic()
        self.recorder = None
        self.state = None
        return {"ok": True, "target_dir": str(target) if target else None}

    async def _cmd_mark(self, req: dict) -> dict:
        if not self.recorder or not self.recorder.recording:
            return {"ok": False, "error": "não há gravação ativa"}
        ts = time.monotonic() - self.session_start_mono
        from datetime import datetime

        m = Mark(
            ts_seconds=round(ts, 2),
            iso_time=datetime.now().isoformat(timespec="seconds"),
            text=req.get("text", "")[:200],
        )
        self.marks.append(m)
        self.state.marks = self.marks
        self.state.save()
        notify(
            "📍 Marca registrada",
            f"[{int(ts // 60):02d}:{int(ts % 60):02d}] {m.text or '(sem texto)'}",
            icon="bookmark-new",
            transient=True,
        )
        return {"ok": True, "mark": asdict(m)}

    async def _cmd_status(self, req: dict) -> dict:
        if not self.recorder or not self.recorder.recording:
            return {
                "ok": True,
                "recording": False,
                "since_last_stop_seconds": int(time.monotonic() - self.last_stop_mono)
                if self.last_stop_mono
                else None,
            }
        elapsed = time.monotonic() - self.session_start_mono
        return {
            "ok": True,
            "recording": True,
            "session_id": self.state.session_id,
            "subject": self.state.subject,
            "elapsed_seconds": int(elapsed),
            "segments": len(self.state.segments),
            "marks": len(self.marks),
            "auto_started": self.state.auto_started,
        }

    async def _cmd_quit(self, req: dict) -> dict:
        asyncio.get_event_loop().call_later(0.5, lambda: os.kill(os.getpid(), signal.SIGTERM))
        return {"ok": True, "shutting_down": True}

    async def _cmd_reload_config(self, req: dict) -> dict:
        """Re-lê config.toml e atualiza atributos.

        Aplica imediatamente em parâmetros sem efeito retroativo (bitrate, layout,
        max_segment se nova gravação). Gravação em curso mantém valores que
        começou (evita merge inconsistente).
        """
        from datetime import datetime

        new_cfg = load_config()
        changed = []
        if new_cfg["recording"]["bitrate"] != self.bitrate:
            changed.append(f"bitrate: {self.bitrate} → {new_cfg['recording']['bitrate']}")
            self.bitrate = new_cfg["recording"]["bitrate"]
        if new_cfg["recording"]["layout"] != self.layout:
            changed.append(f"layout: {self.layout} → {new_cfg['recording']['layout']}")
            self.layout = new_cfg["recording"]["layout"]
        if new_cfg["recording"]["max_segment"] != self.max_segment:
            changed.append(f"max_segment: {self.max_segment} → {new_cfg['recording']['max_segment']}")
            self.max_segment = new_cfg["recording"]["max_segment"]
        if new_cfg["transcriber"]["language"] != self.language:
            changed.append(f"language: {self.language} → {new_cfg['transcriber']['language']}")
            self.language = new_cfg["transcriber"]["language"]
        self.config = new_cfg
        log.info("config recarregada: %s", changed or "nada mudou")
        return {
            "ok": True,
            "reloaded_at": datetime.now().isoformat(timespec="seconds"),
            "changes": changed,
        }

    # ── background loops ───────────────────────────────────────────────────
    async def _watchdog_loop(self) -> None:
        last_silence_check = 0.0
        while True:
            await asyncio.sleep(2)
            if not self.recorder or not self.recorder.recording:
                continue
            now = time.monotonic()
            elapsed = now - self.session_start_mono

            if elapsed >= HARD_CAP_SECONDS:
                log.warning("hard cap atingido — stop forçado")
                notify(
                    "⛔ Hard cap atingido",
                    f"Gravação parada (limite {HARD_CAP_SECONDS // 3600}h).",
                    urgency="critical",
                )
                await self._cmd_stop({})
                continue

            event = self.recorder.watchdog_tick()
            if event == "died":
                notify("⚠️ ffmpeg morreu", "Gravação encerrada.", urgency="critical")
                await self._cmd_stop({})
                continue

            if now - self._reminder_last_mono >= REMINDER_INTERVAL:
                self._reminder_last_mono = now
                mins = int(elapsed / 60)
                notify(
                    "🔴 ainda gravando",
                    f"{mins}min · {self.state.subject}",
                    icon="media-record",
                    transient=True,
                )

            if now - last_silence_check >= SILENCE_CHECK_INTERVAL:
                last_silence_check = now
                db = await asyncio.get_event_loop().run_in_executor(
                    None,
                    measure_mic_db,
                    self.state.mic_source,
                    2,
                )
                if db is not None:
                    if db < SILENCE_THRESHOLD_DB:
                        self.silence_streak += SILENCE_CHECK_INTERVAL
                        log.debug("silêncio: %.1fdB streak=%.0fs", db, self.silence_streak)
                        if self.silence_streak >= SILENCE_MAX_SECONDS:
                            notify(
                                "🟡 Silêncio prolongado",
                                f"Mic abaixo de {SILENCE_THRESHOLD_DB}dB "
                                f"por {SILENCE_MAX_SECONDS // 60}min — parando.",
                            )
                            await self._cmd_stop({})
                    else:
                        self.silence_streak = 0.0

    async def _auto_detect_loop(self) -> None:
        """Event-driven: acorda em eventos `pactl subscribe` OU tick de liveness.

        Em vez de polling cego a cada 5s, ouvimos eventos do PulseAudio (novos
        source-outputs = app começou a usar mic). Tick de liveness garante
        recovery se a subscribe morrer, e ainda permite re-checagem para o
        filtro `min_mic_duration_seconds`.
        """
        self._auto_detect_event = asyncio.Event()
        sub_task = asyncio.create_task(self._pactl_subscribe_loop(), name="pactl-subscribe")
        self._tasks.append(sub_task)

        while True:
            cfg = load_auto_detect_config()
            poll = cfg.get("poll_interval_seconds", 5)
            min_dur = cfg.get("min_mic_duration_seconds", 8)
            # Tick liveness: max(poll, min_dur) — garante que conseguimos
            # confirmar persistência mesmo sem novos eventos.
            tick = max(poll, min_dur)

            try:
                await asyncio.wait_for(self._auto_detect_event.wait(), timeout=tick)
            except TimeoutError:
                pass  # fallback periódico — comportamento legacy garantido
            self._auto_detect_event.clear()

            if not cfg.get("enabled", False):
                continue
            if self.recorder and self.recorder.recording:
                continue
            quiet = cfg.get("quiet_period_after_stop_minutes", 5) * 60
            if self.last_stop_mono and (time.monotonic() - self.last_stop_mono) < quiet:
                continue

            app = await asyncio.get_event_loop().run_in_executor(
                self._pipeline_executor,
                detect_active_call,
                cfg,
            )
            if not app:
                self._auto_detect_first_seen.clear()
                continue

            first = self._auto_detect_first_seen.get(app)
            now = time.monotonic()
            if first is None:
                self._auto_detect_first_seen[app] = now
                continue
            if now - first < min_dur:
                continue
            self._auto_detect_first_seen.clear()
            log.info("auto-detect: %s ativo — iniciando gravação", app)
            await self._cmd_start({"auto": True, "subject": detect_subject()})

    async def _pactl_subscribe_loop(self) -> None:
        """Roda `pactl subscribe`, marca evento quando há atividade source-output.

        Reinicia em loop se pactl morrer (ex: PulseAudio restart). Falha
        silenciosa se pactl não existir — auto-detect ainda funciona via
        polling fallback do _auto_detect_loop.
        """
        while True:
            try:
                proc = await asyncio.create_subprocess_exec(
                    "pactl",
                    "subscribe",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                    env={**os.environ, "LANG": "C", "LC_ALL": "C"},
                )
            except FileNotFoundError:
                log.warning("pactl ausente — auto-detect só com polling fallback")
                return

            try:
                assert proc.stdout is not None
                while True:
                    line = await proc.stdout.readline()
                    if not line:
                        log.warning("pactl subscribe encerrou (rc=%s) — retry em 5s", proc.returncode)
                        break
                    decoded = line.decode("utf-8", errors="ignore")
                    # Eventos relevantes: source-output (cliente começou/parou de capturar)
                    if "source-output" in decoded:
                        if hasattr(self, "_auto_detect_event"):
                            self._auto_detect_event.set()
            finally:
                if proc.returncode is None:
                    proc.terminate()
                    try:
                        await asyncio.wait_for(proc.wait(), timeout=2)
                    except TimeoutError:
                        proc.kill()
            await asyncio.sleep(5)  # backoff antes de re-subscrever
