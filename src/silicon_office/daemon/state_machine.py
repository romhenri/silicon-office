"""Pure hook-event -> AgentRecord transition logic. No I/O, fully unit-testable.

PostToolUse deliberately leaves state as WORKING without changing state_since --
the turn may continue with more tool calls, and Stop is what actually marks
Idle. PermissionRequest is the RF-05 trigger for the Asking highlight.
Subagent events fold into the parent record (MVP: no separate avatar for
subagents) using a label stack so the parent's prior action_label is restored
exactly, rather than guessed, once the subagent finishes.
"""

from __future__ import annotations

import os
from typing import Optional

from silicon_office.common.constants import (
    STATE_ASKING,
    STATE_ERROR,
    STATE_IDLE,
    STATE_WORKING,
)
from silicon_office.common.schema import AgentRecord, HookEvent

TOOL_LABELS = {
    "Bash": "Bash Execution",
    "Read": "Reading File",
    "Write": "Editing File",
    "Edit": "Editing File",
    "Grep": "Searching",
    "Glob": "Searching",
    "WebFetch": "Web Research",
    "WebSearch": "Web Research",
    "Task": "Delegating to subagent",
}


def label_for_tool(tool_name: Optional[str]) -> str:
    if not tool_name:
        return "Working"
    return TOOL_LABELS.get(tool_name, f"Using {tool_name}")


def project_name_from_cwd(cwd: str) -> str:
    if not cwd:
        return "unknown"
    return os.path.basename(cwd.rstrip("/")) or cwd


def apply_event(
    record: Optional[AgentRecord], event: HookEvent, now: float
) -> tuple[Optional[AgentRecord], str]:
    """Returns (record_or_None, op) where op is one of "upsert"/"remove"/"noop".

    `record` is the existing AgentRecord for event.session_id, or None if this
    is the first event ever seen for that session (either a real SessionStart,
    or -- defensively -- any other event whose SessionStart was missed/raced).
    """
    is_new = record is None
    if is_new:
        record = AgentRecord(
            session_id=event.session_id,
            project_name=project_name_from_cwd(event.cwd),
            cwd=event.cwd,
            pid=None,
            entrypoint="unknown",
            state=STATE_IDLE,
            action_label="Idle",
            state_since=now,
        )
    elif event.cwd:
        record.cwd = event.cwd

    name = event.hook_event_name
    op = "upsert"

    if name == "SessionStart":
        record.state = STATE_IDLE
        record.action_label = "Idle"
        record.state_since = now
    elif name == "UserPromptSubmit":
        record.state = STATE_WORKING
        record.action_label = "Processing prompt"
        record.state_since = now
    elif name == "PreToolUse":
        record.state = STATE_WORKING
        record.action_label = label_for_tool(event.tool_name)
        record.state_since = now
    elif name == "PostToolUse":
        if record.state != STATE_WORKING:
            record.state = STATE_WORKING
            record.state_since = now
    elif name == "PostToolUseFailure":
        record.state = STATE_ERROR
        record.action_label = f"Tool error: {event.tool_name or 'unknown'}"
        record.state_since = now
    elif name == "PermissionRequest":
        record.state = STATE_ASKING
        record.action_label = f"Awaiting approval: {event.tool_name or 'tool'}"
        record.state_since = now
    elif name == "Stop":
        record.state = STATE_IDLE
        record.action_label = "Idle"
        record.state_since = now
    elif name == "StopFailure":
        record.state = STATE_ERROR
        record.action_label = "Session error (API failure)"
        record.state_since = now
    elif name == "SubagentStart":
        record.label_stack.append(record.action_label)
        record.state = STATE_WORKING
        record.action_label = f"Working: subagent ({event.agent_type or 'agent'})"
        record.state_since = now
    elif name == "SubagentStop":
        record.action_label = record.label_stack.pop() if record.label_stack else "Working"
        record.state_since = now
    elif name == "SessionEnd":
        return None, "remove"
    else:
        # Unknown/unhandled event name: a brand-new session is still worth
        # registering (auto-create policy) even via an event we don't map,
        # but for an already-known session this is a genuine no-op.
        op = "upsert" if is_new else "noop"

    return record, op
