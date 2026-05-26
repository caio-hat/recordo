"""Modelo de dados (Segment, Mark, SessionState) + Recorder."""

from __future__ import annotations

import atexit
import json
import logging
import os
import re
import signal
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from .config import LOCKFILE, SESSION_META
from .ffmpeg_cmds import build_capture_cmd, build_concat_cmd, build_merge_cmd

log = logging.getLogger(__name__)


# ── Dataclasses ─────────────────────────────────────────────────────────────
@dataclass
class Segment:
    index: int
    started_at: str
    sys_file: str
    mic_file: str
    merged_file: str
    duration: float = 0.0
    size_bytes: int = 0
    status: str = "pending"  # pending|recording|merged|empty|error
    layout: str = "merge"  # merge|split — capturado quando o segmento foi mergeado
    bitrate: str = "32k"


@dataclass
class Mark:
    ts_seconds: float
    iso_time: str
    text: str = ""


@dataclass
class SessionState:
    subject: str
    session_id: str
    started_at: str
    output_dir: str
    mic_source: str
    sys_source: str
    codec: str
    bitrate: str
    layout: str
    segments: list[Segment] = field(default_factory=list)
    marks: list[Mark] = field(default_factory=list)
    finished: bool = False
    auto_started: bool = False

    def save(self) -> None:
        (Path(self.output_dir) / SESSION_META).write_text(
            json.dumps(asdict(self), indent=2, ensure_ascii=False)
        )

    @classmethod
    def load(cls, dir_: Path) -> SessionState:
        data = json.loads((dir_ / SESSION_META).read_text())
        segs = [Segment(**s) for s in data.pop("segments", [])]
        marks = [Mark(**m) for m in data.pop("marks", [])]
        return cls(segments=segs, marks=marks, **data)


# ── Recorder ────────────────────────────────────────────────────────────────
class Recorder:
    """Gerencia ffmpeg processes paralelos e ciclo de segmentos."""

    def __init__(self, state: SessionState, *, max_segment: int, layout: str):
        self.state = state
        self.max_segment = max_segment
        self.layout = layout
        self.dir = Path(state.output_dir)
        self.proc_sys: subprocess.Popen | None = None
        self.proc_mic: subprocess.Popen | None = None
        self.seg_start_mono: float = 0.0
        self.current: Segment | None = None
        self.recording = False

    def start_segment(self) -> None:
        if self.recording:
            return
        idx = len(self.state.segments)
        seg = Segment(
            index=idx,
            started_at=datetime.now().isoformat(timespec="seconds"),
            sys_file=str(self.dir / f"seg{idx:03d}_system.opus"),
            mic_file=str(self.dir / f"seg{idx:03d}_mic.opus"),
            merged_file=str(self.dir / f"seg{idx:03d}_merged.opus"),
            status="recording",
            layout=self.layout,
            bitrate=self.state.bitrate,
        )
        self.current = seg

        cmd_sys = build_capture_cmd(
            self.state.sys_source,
            Path(seg.sys_file),
            max_seconds=self.max_segment,
            bitrate=self.state.bitrate,
        )
        cmd_mic = build_capture_cmd(
            self.state.mic_source,
            Path(seg.mic_file),
            max_seconds=self.max_segment,
            bitrate=self.state.bitrate,
        )

        log.info("iniciando segmento %d", idx)
        self.proc_sys = subprocess.Popen(cmd_sys, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        self.proc_mic = subprocess.Popen(cmd_mic, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        self.seg_start_mono = time.monotonic()
        self.recording = True

    def _terminate(self, proc: subprocess.Popen | None) -> None:
        if not proc or proc.poll() is not None:
            return
        try:
            proc.send_signal(signal.SIGINT)
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            log.warning("ffmpeg pid=%s não saiu com SIGINT, mandando SIGTERM", proc.pid)
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()

    def stop_segment(self) -> Segment | None:
        if not self.recording or not self.current:
            return None
        self._terminate(self.proc_sys)
        self._terminate(self.proc_mic)
        self.recording = False

        seg = self.current
        seg.duration = round(time.monotonic() - self.seg_start_mono, 2)
        if self._merge(seg):
            seg.size_bytes = Path(seg.merged_file).stat().st_size
            seg.status = "merged" if seg.size_bytes > 0 else "empty"
        else:
            seg.status = "empty"

        self.state.segments.append(seg)
        self.state.save()
        self.current = None
        return seg

    def _merge(self, seg: Segment) -> bool:
        cmd = build_merge_cmd(
            Path(seg.sys_file), Path(seg.mic_file), Path(seg.merged_file), seg.layout, seg.bitrate
        )
        if not cmd:
            seg.status = "empty"
            log.warning("segmento %d sem áudio (mic e sys vazios)", seg.index)
            return False
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
            return True
        except subprocess.CalledProcessError as e:
            seg.status = "error"
            log.error("erro merge segmento %d: %s", seg.index, e.stderr)
            return False

    def watchdog_tick(self) -> str | None:
        """Chamado periodicamente. Retorna 'cycled'/'died' se algo aconteceu."""
        if not self.recording:
            return None
        elapsed = time.monotonic() - self.seg_start_mono
        if elapsed >= self.max_segment - 0.5:
            log.info("max_segment atingido — fechando segmento e abrindo novo")
            self.stop_segment()
            self.start_segment()
            return "cycled"
        dead = []
        if self.proc_sys and self.proc_sys.poll() is not None:
            dead.append("sys")
        if self.proc_mic and self.proc_mic.poll() is not None:
            dead.append("mic")
        if len(dead) == 2:
            log.error("ambos ffmpeg morreram — encerrando segmento")
            self.stop_segment()
            return "died"
        return None

    def finalize(self) -> Path | None:
        """Encerra gravação e concatena segmentos válidos."""
        if self.recording:
            self.stop_segment()
        merged = [
            Path(s.merged_file)
            for s in self.state.segments
            if s.status == "merged" and Path(s.merged_file).exists()
        ]
        if not merged:
            log.warning("nenhum segmento válido — nada para concatenar")
            return None
        safe = re.sub(r"[^A-Za-z0-9_-]+", "_", self.state.subject).strip("_") or "Gravacao"
        final = self.dir / f"{safe}_{self.state.session_id}.opus"
        list_file = self.dir / "_concat_list.txt"

        # Heterogeneidade força reencode (caso edge: layout/bitrate trocou no meio)
        valid_segs = [s for s in self.state.segments if s.status == "merged"]
        layouts = {s.layout for s in valid_segs}
        bitrates = {s.bitrate for s in valid_segs}
        heterogeneous = len(layouts) > 1 or len(bitrates) > 1
        if heterogeneous:
            log.info("concat com reencode (segmentos heterogêneos: layouts=%s bitrates=%s)",
                     layouts, bitrates)
        cmd = build_concat_cmd(
            merged, list_file, final, bitrate=self.state.bitrate, reencode=heterogeneous,
        )
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
            self.state.finished = True
            self.state.save()
            return final
        except subprocess.CalledProcessError as e:
            log.error("erro no concat final: %s", e.stderr)
            return None


# ── Helpers de sessão ───────────────────────────────────────────────────────
def make_session(
    subject: str, mic: str, sys_: str, *, bitrate: str, layout: str, base_dir: Path
) -> SessionState:
    safe = re.sub(r"[^A-Za-z0-9 ]+", "", subject).strip().replace(" ", "_") or "Gravacao"
    sid = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = base_dir / f"{safe}_{sid}"
    out.mkdir(parents=True, exist_ok=True)
    return SessionState(
        subject=subject,
        session_id=sid,
        started_at=datetime.now().isoformat(timespec="seconds"),
        output_dir=str(out),
        mic_source=mic,
        sys_source=sys_,
        codec="opus",
        bitrate=bitrate,
        layout=layout,
    )


def find_resumable(base_dir: Path) -> Path | None:
    if not base_dir.exists():
        return None
    candidates = sorted(base_dir.glob("*/session.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for c in candidates:
        try:
            data = json.loads(c.read_text())
            if not data.get("finished"):
                return c.parent
        except Exception:
            continue
    return None


def write_report(state: SessionState, final: Path | None) -> None:
    rep = Path(state.output_dir) / f"{state.session_id}_report.md"
    lines = [
        f"# Relatório — {state.subject}",
        "",
        f"- **ID sessão:** `{state.session_id}`",
        f"- **Início:** {state.started_at}",
        f"- **Fontes:** mic=`{state.mic_source}` · sys=`{state.sys_source}`",
        f"- **Codec:** {state.codec} @ {state.bitrate} ({state.layout})",
        f"- **Segmentos:** {len(state.segments)}",
        f"- **Arquivo final:** {'`' + final.name + '`' if final else '*(não gerado)*'}",
        "",
        "| # | Início | Duração (s) | Tamanho | Status |",
        "|---|---|---|---|---|",
    ]
    for s in state.segments:
        size_h = f"{s.size_bytes / 1024:.1f} KB" if s.size_bytes else "-"
        lines.append(f"| {s.index} | {s.started_at} | {s.duration:.1f} | {size_h} | {s.status} |")
    rep.write_text("\n".join(lines) + "\n")


# ── Lockfile + sinais (modo standalone CLI) ─────────────────────────────────
_recorder_ref: Recorder | None = None


def acquire_lock() -> None:
    """Impede instância dupla no modo standalone. Daemon não usa (tem socket)."""
    if LOCKFILE.exists():
        try:
            pid = int(LOCKFILE.read_text().strip())
            os.kill(pid, 0)
            log.error("já existe instância rodando (PID %d) — abortando", pid)
            sys.exit(1)
        except (ProcessLookupError, ValueError):
            log.warning("lockfile órfão — removendo")
            LOCKFILE.unlink(missing_ok=True)
    LOCKFILE.write_text(str(os.getpid()))
    atexit.register(LOCKFILE.unlink, missing_ok=True)


def set_recorder_ref(rec: Recorder | None) -> None:
    global _recorder_ref
    _recorder_ref = rec


def _global_cleanup() -> None:
    if _recorder_ref and _recorder_ref.recording:
        log.warning("cleanup atexit — parando segmento em andamento")
        _recorder_ref.stop_segment()


def _signal_handler(signum, _frame) -> None:
    log.warning("recebido signal %d — encerrando", signum)
    _global_cleanup()
    sys.exit(128 + signum)


def install_signals() -> None:
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, _signal_handler)
    atexit.register(_global_cleanup)
