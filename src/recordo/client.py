"""Cliente do daemon via UNIX socket (JSON-lines)."""

from __future__ import annotations

import json
import socket
from typing import Any

from .config import SOCKET_PATH


def send_to_daemon(cmd: str, **kwargs: Any) -> dict:
    """Envia 1 comando JSON-line ao socket e retorna resposta."""
    if not SOCKET_PATH.exists():
        return {"ok": False, "error": f"daemon não está rodando (socket {SOCKET_PATH} ausente)"}
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(10)
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
