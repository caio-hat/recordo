"""Detecção de fontes PulseAudio/PipeWire (pactl) e clients de mic."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass


def _has_command(name: str) -> bool:
    return shutil.which(name) is not None


@dataclass
class AudioSource:
    name: str
    description: str
    state: str

    @property
    def kind(self) -> str:
        n = self.name.lower()
        if n.endswith(".monitor"):
            return "system"
        if "input" in n or n.endswith(".source") or ".source." in n:
            return "mic"
        return "unknown"

    @property
    def score(self) -> int:
        n = self.name.lower()
        s = 0
        if "bluez" in n:
            s += 100
        elif "usb" in n:
            s += 50
        if self.state == "RUNNING":
            s += 30
        if "monitor" in n and "default" in n:
            s += 10
        return s


def _pactl_env() -> dict[str, str]:
    return {**os.environ, "LANG": "C", "LC_ALL": "C"}


def list_sources() -> list[AudioSource]:
    """Lista fontes via `pactl list sources` (LANG=C pra parser estável)."""
    try:
        out = subprocess.check_output(
            ["pactl", "list", "sources"],
            text=True,
            env=_pactl_env(),
            timeout=5,
        )
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return []

    sources: list[AudioSource] = []
    cur: dict[str, str] = {}
    for line in out.splitlines():
        if re.match(r"^Source #\d+", line):
            if cur.get("name"):
                sources.append(AudioSource(cur["name"], cur.get("desc", ""), cur.get("state", "")))
            cur = {}
        elif m := re.match(r"\s*Name:\s*(.+)$", line):
            cur["name"] = m.group(1).strip()
        elif m := re.match(r"\s*Description:\s*(.+)$", line):
            cur["desc"] = m.group(1).strip()
        elif m := re.match(r"\s*State:\s*(.+)$", line):
            cur["state"] = m.group(1).strip()
    if cur.get("name"):
        sources.append(AudioSource(cur["name"], cur.get("desc", ""), cur.get("state", "")))
    return sources


def auto_pick(sources: list[AudioSource]) -> tuple[str | None, str | None]:
    """Escolhe mic + sys por score (Bluetooth > USB > builtin, RUNNING > suspended)."""
    mics = sorted([s for s in sources if s.kind == "mic"], key=lambda s: -s.score)
    sys_ = sorted([s for s in sources if s.kind == "system"], key=lambda s: -s.score)
    return (mics[0].name if mics else None, sys_[0].name if sys_ else None)


def list_source_outputs() -> list[dict]:
    """Lista clients capturando mic agora.

    Returns lista de dicts com keys: source_id, state, app_name, binary, corked.
    """
    try:
        out = subprocess.check_output(
            ["pactl", "list", "source-outputs"],
            text=True,
            env=_pactl_env(),
            timeout=3,
        )
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return []

    entries: list[dict] = []
    cur: dict = {}
    for line in out.splitlines():
        if re.match(r"^Source Output #\d+", line):
            if cur:
                entries.append(cur)
            cur = {}
        elif m := re.match(r"\s*application\.name\s*=\s*\"([^\"]+)\"", line):
            cur["app_name"] = m.group(1)
        elif m := re.match(r"\s*application\.process\.binary\s*=\s*\"([^\"]+)\"", line):
            cur["binary"] = m.group(1)
        elif m := re.match(r"\s*Source:\s*(\d+)", line):
            cur["source_id"] = m.group(1)
        # B2: capturar state (RUNNING/CORKED/IDLE)
        elif m := re.match(r"\s*State:\s*(\w+)", line):
            cur["state"] = m.group(1)
        elif m := re.match(r"\s*Corked:\s*(\w+)", line):
            cur["corked"] = m.group(1).lower() == "yes"
    if cur:
        entries.append(cur)
    return entries


def list_sink_inputs() -> list[dict]:
    """B2: Lista clients reproduzindo áudio (output stream).

    Útil para detectar áudio CHEGANDO de uma reunião (interlocutor falando)
    mesmo se nosso mic está mudo. Returns lista de dicts com:
      sink_id, state, app_name, binary, corked, volume_pct
    """
    try:
        out = subprocess.check_output(
            ["pactl", "list", "sink-inputs"],
            text=True,
            env=_pactl_env(),
            timeout=3,
        )
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return []

    entries: list[dict] = []
    cur: dict = {}
    for line in out.splitlines():
        if re.match(r"^Sink Input #\d+", line):
            if cur:
                entries.append(cur)
            cur = {}
        elif m := re.match(r"\s*application\.name\s*=\s*\"([^\"]+)\"", line):
            cur["app_name"] = m.group(1)
        elif m := re.match(r"\s*application\.process\.binary\s*=\s*\"([^\"]+)\"", line):
            cur["binary"] = m.group(1)
        elif m := re.match(r"\s*Sink:\s*(\d+)", line):
            cur["sink_id"] = m.group(1)
        elif m := re.match(r"\s*State:\s*(\w+)", line):
            cur["state"] = m.group(1)
        elif m := re.match(r"\s*Corked:\s*(\w+)", line):
            cur["corked"] = m.group(1).lower() == "yes"
        elif m := re.match(r"\s*Volume:.+?(\d+)%", line):
            cur["volume_pct"] = int(m.group(1))
    if cur:
        entries.append(cur)
    return entries


# B2: Whitelist robusta de apps de reunião (process binary names)
DEFAULT_MEETING_APPS = [
    # Native desktop apps
    "teams-for-linux",
    "ms-teams",
    "msteams",
    "zoom",
    "zoom-us",
    "slack",
    "slack-canary",
    "discord",
    "discord-canary",
    "discord-ptb",
    "Discord",
    "WebexTeams",
    "WebexLinux",
    "webex",
    "skype",
    "skypeforlinux",
    "element-desktop",
    "element-electron",
    "Element",
    "signal-desktop",
    "obs",
    "obs-studio",
    "OBS Studio",
    "krfb",
    "krdc",  # remote desktop / screen share
    "audacity",
    "thunderbird",
    # Browsers (Teams web / Meet / Zoom web / Whereby / Jitsi)
    "firefox",
    "firefox-esr",
    "chromium",
    "chromium-browser",
    "Chromium",
    "google-chrome",
    "google-chrome-stable",
    "google-chrome-beta",
    "Google Chrome",
    "brave-browser",
    "brave",
    "vivaldi",
    "vivaldi-stable",
    "WebKitWebProcess",
    "epiphany",  # GNOME Web
    # Screen recorders (often used in meetings)
    "kazam",
    "simplescreenrecorder",
]


@dataclass
class MeetingSignal:
    """B2: Resultado da detecção multi-sinal de reunião ativa."""

    in_meeting: bool
    confidence: float  # 0..1
    reason: str  # human-readable
    signals_active: list[str]  # ex: ["mic_used_by_firefox", "speaker_active_zoom"]
    apps_detected: list[str]  # ex: ["firefox", "zoom"]


def detect_meeting(cfg: dict | None = None) -> MeetingSignal:
    """B2: Detecta call ativa via PulseAudio signals (funciona minimizado).

    Sinais combinados:
      Sig1 (peso 0.9): source-output RUNNING != recordo
                       (alguém usando microfone)
      Sig2 (peso 0.7): sink-input RUNNING + binary whitelist + audio
                       sendo emitido (volume_pct > 0)
                       (áudio chegando da call, mesmo se mic mudo)

    Window title / wmctrl NÃO usado — quebraria com janela minimizada.

    Args:
        cfg: dict com 'meeting_apps' (lista whitelist). Se None, usa default.

    Returns:
        MeetingSignal. in_meeting=True se sig1 OR sig2.
    """
    if cfg is None:
        cfg = {}
    meeting_apps = cfg.get("meeting_apps", DEFAULT_MEETING_APPS)
    meeting_apps_lower = {a.lower() for a in meeting_apps}

    signals_active: list[str] = []
    apps_detected: list[str] = []
    confidence = 0.0

    # Sig1: source-output RUNNING (alguém capturando mic)
    for entry in list_source_outputs():
        if entry.get("state") != "RUNNING":
            continue
        if entry.get("corked"):
            continue
        binary = (entry.get("binary") or "").lower()
        app = (entry.get("app_name") or "").lower()
        # Excluir nosso próprio recording
        if "recordo" in app or "recordo" in binary or "ffmpeg" in binary:
            continue
        # Match em whitelist (binary direto OR substring)
        is_meeting = (
            binary in meeting_apps_lower
            or app in meeting_apps_lower
            or any(a in binary for a in meeting_apps_lower if len(a) > 3)
            or any(a in app for a in meeting_apps_lower if len(a) > 3)
        )
        if is_meeting or binary or app:
            # Mic em uso por outro app SEMPRE conta como sinal forte
            signals_active.append(f"mic_used_by_{binary or app}")
            apps_detected.append(binary or app)
            confidence = max(confidence, 0.9)

    # Sig2: sink-input RUNNING + meeting app + audio passing
    for entry in list_sink_inputs():
        if entry.get("state") != "RUNNING":
            continue
        if entry.get("corked"):
            continue
        binary = (entry.get("binary") or "").lower()
        app = (entry.get("app_name") or "").lower()
        # Skip nosso próprio playback
        if "recordo" in app or "recordo" in binary:
            continue
        # Match meeting app
        is_meeting = (
            binary in meeting_apps_lower
            or app in meeting_apps_lower
            or any(a in binary for a in meeting_apps_lower if len(a) > 3)
            or any(a in app for a in meeting_apps_lower if len(a) > 3)
        )
        if not is_meeting:
            continue
        volume = entry.get("volume_pct", 100)
        # Apenas considera ativo se volume > 0 (não muted)
        if volume > 0:
            signals_active.append(f"speaker_active_{binary or app}")
            apps_detected.append(binary or app)
            confidence = max(confidence, 0.7)

    # Boost confidence se múltiplos sinais
    n_sigs = len(signals_active)
    if n_sigs > 1:
        confidence = min(1.0, confidence + 0.1 * (n_sigs - 1))

    in_meeting = confidence >= 0.5
    if in_meeting:
        reason = f"{n_sigs} sinal(is): {', '.join(signals_active[:3])}"
    else:
        reason = "Nenhum sinal de reunião detectado"

    return MeetingSignal(
        in_meeting=in_meeting,
        confidence=confidence,
        reason=reason,
        signals_active=signals_active,
        apps_detected=list(set(apps_detected)),
    )


def detect_active_call(cfg: dict) -> str | None:
    """Retorna nome do app de call ativo, ou None.

    Match contra cfg['apps'] (case-insensitive, substring). Bloqueia cfg['deny_apps'].
    """
    outputs = list_source_outputs()
    if not outputs:
        return None
    allow = {a.lower() for a in cfg.get("apps", [])}
    deny = {a.lower() for a in cfg.get("deny_apps", [])}
    for entry in outputs:
        for c in (entry.get("app_name", ""), entry.get("binary", "")):
            cl = c.lower()
            if not cl:
                continue
            if cl in deny:
                return None
            if cl in allow or any(a in cl for a in allow):
                return c
    return None


def measure_mic_db(source: str, sample_seconds: int = 1) -> float | None:
    """RMS dB do mic via `parec` (cliente nativo PulseAudio, leve).

    Por que não ffmpeg+volumedetect:
      ffmpeg abre um segundo stream de captura, o que em hardware limitado
      pode disparar reconfig do device e dropar samples no recorder principal.
      `parec` é parte do `pulseaudio-utils` (já é dep do setup.sh) e
      compartilha a source com baixíssima latência.

    Implementação:
      Lemos `sample_seconds` segundos de PCM s16le mono @16kHz, calculamos
      RMS, convertemos pra dBFS. Retorna None se falhar.

    Fallback:
      Se parec sumir do PATH ou falhar, tenta ffmpeg+volumedetect (legacy).
    """
    db = _measure_mic_db_parec(source, sample_seconds)
    if db is not None:
        return db
    return _measure_mic_db_ffmpeg(source, sample_seconds)


def _measure_mic_db_parec(source: str, sample_seconds: int) -> float | None:
    """RMS via parec (preferido)."""
    if not _has_command("parec"):
        return None
    rate = 16000
    channels = 1
    cmd = [
        "parec",
        "--device",
        source,
        "--rate",
        str(rate),
        "--channels",
        str(channels),
        "--format",
        "s16le",
        "--raw",
    ]
    expected_bytes = rate * channels * 2 * sample_seconds
    try:
        # Inicia parec, lê N bytes, mata. Mais barato que rodar ffmpeg full.
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        try:
            data = b""
            deadline = sample_seconds + 1.0
            import time as _time

            start = _time.monotonic()
            while len(data) < expected_bytes and (_time.monotonic() - start) < deadline:
                chunk = proc.stdout.read(min(4096, expected_bytes - len(data)))  # type: ignore[union-attr]
                if not chunk:
                    break
                data += chunk
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                proc.kill()
    except (FileNotFoundError, OSError):
        return None
    if len(data) < 2:
        return None

    return _rms_dbfs_s16le(data)


def _rms_dbfs_s16le(data: bytes) -> float:
    """RMS em dBFS para PCM s16 little-endian."""
    import array
    import math

    samples = array.array("h")
    samples.frombytes(data[: (len(data) // 2) * 2])
    if not samples:
        return -100.0
    n = len(samples)
    # Cálculo manual evita dep de numpy. Para 16k/1s = 16k iterações, OK.
    sumsq = 0
    for s in samples:
        sumsq += s * s
    rms = math.sqrt(sumsq / n)
    if rms < 1e-9:
        return -100.0
    # 32768 = max int16 (full scale)
    return 20 * math.log10(rms / 32768.0)


def _measure_mic_db_ffmpeg(source: str, sample_seconds: int) -> float | None:
    """Legacy fallback: ffmpeg + volumedetect."""
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-nostats",
        "-f",
        "pulse",
        "-i",
        source,
        "-t",
        str(sample_seconds),
        "-af",
        "volumedetect",
        "-f",
        "null",
        "-",
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=sample_seconds + 5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if m := re.search(r"mean_volume:\s*(-?\d+(?:\.\d+)?)\s*dB", proc.stderr):
        return float(m.group(1))
    return None
