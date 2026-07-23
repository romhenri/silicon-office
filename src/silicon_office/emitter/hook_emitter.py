"""Hook-invoked emitter.

Claude Code runs this as a command hook for every event in
common.constants.TARGET_HOOK_EVENTS. It reads the hook's JSON payload from
stdin, extracts a small summary, and fires it at the daemon over UDP.

This script must NEVER block or fail a real hook invocation: no exception may
propagate, it always exits 0, and it never prints a hookSpecificOutput/decision
-- it is a pure observer, not a participant in Claude's permission flow.
"""

from __future__ import annotations

import json
import sys
import time
from typing import Any, Optional

from silicon_office.common.constants import UDP_HOST, UDP_PORT
from silicon_office.common.ipc import send_udp_fire_and_forget
from silicon_office.common.schema import HookEvent

_SUMMARY_MAX_LEN = 2000
_SUMMARY_KEYS = ("command", "file_path", "pattern", "url", "prompt", "query")


def _summarize_tool_input(tool_input: Any) -> Optional[str]:
    if tool_input is None:
        return None
    if isinstance(tool_input, dict):
        for key in _SUMMARY_KEYS:
            if key in tool_input and isinstance(tool_input[key], str):
                return tool_input[key][:_SUMMARY_MAX_LEN]
        text = str(tool_input)
    else:
        text = str(tool_input)
    return text.replace("\n", " ")[:_SUMMARY_MAX_LEN]


def build_hook_event(payload: dict[str, Any]) -> Optional[HookEvent]:
    session_id = payload.get("session_id")
    hook_event_name = payload.get("hook_event_name")
    if not session_id or not hook_event_name:
        return None
    tool_error = payload.get("tool_error")
    if tool_error is not None:
        tool_error = str(tool_error)[:_SUMMARY_MAX_LEN]
    return HookEvent(
        session_id=str(session_id),
        hook_event_name=str(hook_event_name),
        cwd=str(payload.get("cwd") or ""),
        tool_name=payload.get("tool_name"),
        tool_input_summary=_summarize_tool_input(payload.get("tool_input")),
        tool_error=tool_error,
        agent_id=payload.get("agent_id"),
        agent_type=payload.get("agent_type"),
        ts=time.time(),
    )


def main() -> None:
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw and raw.strip() else {}
        if not isinstance(payload, dict):
            payload = {}
    except Exception:
        payload = {}

    try:
        event = build_hook_event(payload)
        if event is not None:
            send_udp_fire_and_forget(UDP_HOST, UDP_PORT, event.to_dict())
    except Exception:
        pass

    sys.exit(0)


if __name__ == "__main__":
    main()
