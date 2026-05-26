"""Cliente do daemon via UNIX socket (JSON-lines)."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from typing import Any

from .config import SOCKET_PATH


def send_to_daemon(cmd: str, **kwargs: Any) -> dict:
    """Envia 1 comando JSON-line ao socket e retorna resposta."""
    if not SOCKET_PATH.exists():
        return {"ok": False, "error": f"daemon não está rodando (socket {SOCKET_PATH} ausente)"}
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    # 60s: finalize() + concat + post_pipeline (sync) podem demorar em sessão longa
    s.settimeout(60)
    try:
        s.connect(str(SOCKET_PATH))
        payload = json.dumps({"cmd": cmd, **kwargs}, ensure_ascii=False) + "\n"
        s.sendall(payload.encode("utf-8"))
        data = b""
        while not data.endswith(b"\n"):
            chunk = s.recv(4096)
            if not chunk:
                break
            data += chunk
        return json.loads(data.decode("utf-8")) if data else {"ok": False, "error": "sem resposta"}
    except Exception as e:
        return {"ok": False, "error": f"falha socket: {e}"}
    finally:
        s.close()


def is_daemon_alive() -> bool:
    """Probe rápido: socket existe E daemon responde a status."""
    if not SOCKET_PATH.exists():
        return False
    resp = send_to_daemon("status")
    return bool(resp.get("ok"))


def ensure_daemon(timeout: float = 8.0, *, prefer_systemd: bool = True) -> bool:
    """Garante daemon rodando. Idempotente.

    1. Se já vivo, retorna True imediatamente.
    2. Tenta `systemctl --user start recordo` se disponível.
    3. Fallback: spawn `recordo --daemon` em background (nohup-like) com
       stdout/stderr redirecionados pra `/tmp/recordo.daemon.log`.
    4. Polling até `timeout` aguardando socket aparecer.

    Retorna True se daemon ficou up, False se desistiu.
    """
    if is_daemon_alive():
        return True

    started = False
    if prefer_systemd:
        try:
            r = subprocess.run(
                ["systemctl", "--user", "list-unit-files", "recordo.service"],
                capture_output=True,
                text=True,
                timeout=3,
            )
            if r.returncode == 0 and "recordo.service" in r.stdout:
                subprocess.run(
                    ["systemctl", "--user", "start", "recordo"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                started = True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

    if not started:
        # Spawn detached: o daemon é child do PID atual e sobrevive ao exit
        # do client (pelo setsid + double-fork-like via Popen + close_fds).
        log_path = "/tmp/recordo.daemon.log"
        try:
            log_fd = open(log_path, "ab")
            subprocess.Popen(
                [sys.executable, "-m", "recordo", "--daemon"],
                stdout=log_fd,
                stderr=log_fd,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
                close_fds=True,
            )
        except OSError:
            return False

    # Polling até 8s (suficiente p/ asyncio.start_unix_server)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if is_daemon_alive():
            return True
        time.sleep(0.15)
    return False


__all__ = ["ensure_daemon", "is_daemon_alive", "send_to_daemon"]
# os é re-exportado p/ futuras features de diagnóstico do CLI
_ = os
