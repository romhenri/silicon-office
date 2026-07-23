"""Wire message shapes shared by the emitter, daemon, and frontend."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional

WIRE_VERSION = 1


@dataclass
class HookEvent:
    """A single hook invocation, as forwarded by the emitter over UDP."""

    session_id: str
    hook_event_name: str
    cwd: str = ""
    tool_name: Optional[str] = None
    tool_input_summary: Optional[str] = None
    tool_error: Optional[str] = None
    agent_id: Optional[str] = None
    agent_type: Optional[str] = None
    ts: float = 0.0
    v: int = WIRE_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "HookEvent":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known and k != "v"})


@dataclass
class AgentRecord:
    """Authoritative state for one tracked Claude Code session."""

    session_id: str
    project_name: str
    cwd: str
    pid: Optional[int]
    entrypoint: str
    state: str
    action_label: str
    state_since: float
    agent_kind: str = "main"
    parent_session_id: Optional[str] = None
    # internal-only: stack of prior action_labels, used to restore the
    # parent's label when a folded subagent finishes. Not sent to the
    # frontend as a top-level field but harmless if it were.
    label_stack: list[str] = field(default_factory=list)

    def to_wire_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("label_stack", None)
        return d


def make_snapshot_message(agents: dict[str, AgentRecord], ts: float) -> dict[str, Any]:
    return {
        "v": WIRE_VERSION,
        "type": "snapshot",
        "ts": ts,
        "agents": {sid: rec.to_wire_dict() for sid, rec in agents.items()},
    }


def make_diff_message(
    session_id: str, op: str, agent: Optional[AgentRecord], ts: float
) -> dict[str, Any]:
    msg: dict[str, Any] = {
        "v": WIRE_VERSION,
        "type": "diff",
        "ts": ts,
        "session_id": session_id,
        "op": op,
    }
    if agent is not None:
        msg["agent"] = agent.to_wire_dict()
    return msg
