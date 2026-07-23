"""In-memory session registry: the daemon's single source of truth.

Cross-references ~/.claude/sessions/*.json for two things state_machine.py
can't know on its own: the OS pid behind a session_id (needed by the reaper)
and a nicer human project name. Only ever touched from the asyncio event loop
thread -- not thread-safe by design, and doesn't need to be.
"""

from __future__ import annotations

import json
import os
import pathlib
from typing import Optional

from silicon_office.common.schema import AgentRecord, HookEvent
from silicon_office.daemon.state_machine import apply_event as sm_apply_event

SESSIONS_DIR = pathlib.Path.home() / ".claude" / "sessions"


def is_pid_alive(pid: Optional[int]) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, just not ours to signal
    except OSError:
        return False
    return True


def _read_session_files() -> list[dict]:
    if not SESSIONS_DIR.is_dir():
        return []
    out = []
    for path in SESSIONS_DIR.glob("*.json"):
        try:
            out.append(json.loads(path.read_text()))
        except (OSError, json.JSONDecodeError):
            continue
    return out


def find_session_file(session_id: str) -> Optional[dict]:
    for data in _read_session_files():
        if data.get("sessionId") == session_id:
            return data
    return None


def list_live_sessions() -> list[dict]:
    """Cold-start enumeration: sessions/*.json entries whose pid is alive."""
    return [d for d in _read_session_files() if is_pid_alive(d.get("pid"))]


class SessionRegistry:
    def __init__(self) -> None:
        self._agents: dict[str, AgentRecord] = {}

    def all(self) -> dict[str, AgentRecord]:
        return dict(self._agents)

    def get(self, session_id: str) -> Optional[AgentRecord]:
        return self._agents.get(session_id)

    def seed(self, record: AgentRecord) -> None:
        """Register a record found alive at cold-start (no hook fired this)."""
        self._agents[record.session_id] = record

    def apply_event(self, event: HookEvent, now: float) -> tuple[Optional[AgentRecord], str]:
        existing = self._agents.get(event.session_id)
        record, op = sm_apply_event(existing, event, now)
        if op == "remove":
            self._agents.pop(event.session_id, None)
        elif op == "upsert" and record is not None:
            self._resolve_identity(record)
            self._agents[event.session_id] = record
        return record, op

    def _resolve_identity(self, record: AgentRecord) -> None:
        if record.pid is not None:
            return
        info = find_session_file(record.session_id)
        if info:
            record.pid = info.get("pid")
            record.entrypoint = info.get("entrypoint", record.entrypoint)
            if info.get("name"):
                record.project_name = info["name"]

    def resolve_pending_identities(self) -> None:
        """Retry pid/name resolution for records still missing a pid. Called
        periodically by the reaper -- this is the "bounded retry" for the
        SessionStart-vs-sessions/*.json write race, without ever blocking
        the UDP receive path with a sleep."""
        for record in self._agents.values():
            if record.pid is None:
                self._resolve_identity(record)

    def reap_dead(self) -> list[str]:
        """Remove tracked agents whose pid is no longer alive (crash without
        a clean SessionEnd). Returns the removed session_ids."""
        dead = [
            sid
            for sid, rec in self._agents.items()
            if rec.pid is not None and not is_pid_alive(rec.pid)
        ]
        for sid in dead:
            self._agents.pop(sid, None)
        return dead
