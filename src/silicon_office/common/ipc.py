"""NDJSON encoding + buffered line framing shared by every IPC participant.

Two transports use this module:
- UDP (emitter -> daemon): one datagram is one message, no buffering needed.
- TCP (daemon -> frontend): a stream, so reads may be split mid-message or
  coalesce multiple messages into one recv() -- NDJSONBuffer handles both.
"""

from __future__ import annotations

import json
import socket
from typing import Any, Optional


def encode_message(obj: dict[str, Any]) -> bytes:
    return (json.dumps(obj, separators=(",", ":")) + "\n").encode("utf-8")


def decode_message(line: bytes) -> Optional[dict[str, Any]]:
    """Best-effort decode of a single line. Returns None on any failure --
    callers must drop malformed messages rather than propagate the error."""
    try:
        return json.loads(line.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None


class NDJSONBuffer:
    """Accumulates bytes from a stream socket and yields decoded JSON objects.

    Feed it whatever a recv() call returns, in order; it splits on newlines
    and holds back any trailing partial line for the next feed() call.
    """

    def __init__(self) -> None:
        self._buf = b""

    def feed(self, data: bytes) -> list[dict[str, Any]]:
        self._buf += data
        messages: list[dict[str, Any]] = []
        while b"\n" in self._buf:
            line, self._buf = self._buf.split(b"\n", 1)
            if not line.strip():
                continue
            obj = decode_message(line)
            if obj is not None:
                messages.append(obj)
        return messages


def send_udp_fire_and_forget(
    host: str, port: int, obj: dict[str, Any], timeout: float = 0.05
) -> None:
    """Send one JSON message over UDP and never raise or block meaningfully.

    Used by the hook emitter, which must never delay or fail a Claude Code
    hook invocation regardless of whether a daemon is listening.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(timeout)
            sock.sendto(encode_message(obj), (host, port))
    except OSError:
        pass
