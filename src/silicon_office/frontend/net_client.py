"""Background thread owning the TCP connection to the daemon.

Only this thread touches the socket. Parsed messages (and a synthetic
`_conn_status` message on connect/disconnect) are pushed onto a queue.Queue;
the pygame main thread is the only thing that ever drains it and mutates
render state, so no lock is ever held during drawing. Reconnects with
capped, jittered exponential backoff whenever the daemon isn't reachable or
the connection drops -- the render loop keeps drawing last-known state in
the meantime instead of freezing (RNF-04).
"""

from __future__ import annotations

import queue
import random
import socket
import threading
import time
from typing import Any

from silicon_office.common.ipc import NDJSONBuffer

_MIN_BACKOFF = 0.5
_MAX_BACKOFF = 4.0
_RECV_TIMEOUT = 0.5
_CONNECT_TIMEOUT = 2.0


class NetClient:
    def __init__(self, host: str, port: int, out_queue: "queue.Queue[dict[str, Any]]") -> None:
        self._host = host
        self._port = port
        self._queue = out_queue
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        backoff = _MIN_BACKOFF
        while not self._stop.is_set():
            try:
                with socket.create_connection(
                    (self._host, self._port), timeout=_CONNECT_TIMEOUT
                ) as sock:
                    sock.settimeout(_RECV_TIMEOUT)
                    self._queue.put({"type": "_conn_status", "connected": True})
                    backoff = _MIN_BACKOFF
                    self._read_loop(sock)
            except OSError:
                pass
            self._queue.put({"type": "_conn_status", "connected": False})
            if self._stop.is_set():
                break
            time.sleep(backoff + random.uniform(0, backoff * 0.2))
            backoff = min(_MAX_BACKOFF, backoff * 2)

    def _read_loop(self, sock: socket.socket) -> None:
        buffer = NDJSONBuffer()
        while not self._stop.is_set():
            try:
                data = sock.recv(4096)
            except socket.timeout:
                continue
            if not data:
                return  # connection closed by peer
            for message in buffer.feed(data):
                self._queue.put(message)
