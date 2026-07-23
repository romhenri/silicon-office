#!/usr/bin/env python3
"""Verification harness: fabricates Claude Code hook payloads and drives
them into the pipeline, so the daemon+frontend can be exercised through
every state transition without needing real Claude Code sessions.

Two delivery modes:
  --mode via-emitter   pipes JSON into the real hook_emitter.py's stdin as a
                        subprocess -- exercises the true emitter code path.
  --mode direct-udp     builds the HookEvent and sends it straight at the
                        daemon's UDP socket -- faster iteration.

Scenarios:
  full-lifecycle  one agent through SessionStart -> ... -> SessionEnd,
                  pausing at PermissionRequest so the Asking pulse is
                  visible, and passing through PostToolUseFailure so Error
                  coloring is visible too.
  multi           N agents with staggered, randomized transitions, to
                  exercise grid reflow and simultaneous Asking highlights.
  crash           spawns a real short-lived process, registers a throwaway
                  ~/.claude/sessions/<pid>.json for it, and lets it exit
                  without ever sending SessionEnd -- confirms the daemon's
                  reaper independently despawns it via pid liveness checks.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import random
import subprocess
import sys
import time
import uuid

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from silicon_office.common.constants import UDP_HOST, UDP_PORT  # noqa: E402
from silicon_office.common.ipc import send_udp_fire_and_forget  # noqa: E402
from silicon_office.emitter.hook_emitter import build_hook_event  # noqa: E402

SESSIONS_DIR = pathlib.Path.home() / ".claude" / "sessions"


def make_payload(session_id: str, hook_event_name: str, cwd: str, **extra) -> dict:
    payload = {"session_id": session_id, "hook_event_name": hook_event_name, "cwd": cwd}
    payload.update({k: v for k, v in extra.items() if v is not None})
    return payload


def fire(mode: str, payload: dict) -> None:
    if mode == "via-emitter":
        subprocess.run(
            [sys.executable, "-m", "silicon_office.emitter.hook_emitter"],
            input=json.dumps(payload),
            text=True,
            timeout=5,
            cwd=str(pathlib.Path(__file__).resolve().parent.parent / "src"),
        )
    else:
        event = build_hook_event(payload)
        if event is not None:
            send_udp_fire_and_forget(UDP_HOST, UDP_PORT, event.to_dict())


def run_full_lifecycle(mode: str, session_id: str, cwd: str, pace: float, hold: float) -> None:
    steps = [
        ("SessionStart", {}),
        ("UserPromptSubmit", {}),
        ("PreToolUse", {"tool_name": "Bash", "tool_input": {"command": "npm test"}}),
        ("PostToolUse", {"tool_name": "Bash"}),
        ("PreToolUse", {"tool_name": "Read", "tool_input": {"file_path": "/tmp/foo.txt"}}),
        ("PostToolUse", {"tool_name": "Read"}),
        ("PermissionRequest", {"tool_name": "Bash", "tool_input": {"command": "rm -rf build"}}),
        ("PostToolUseFailure", {"tool_name": "Bash", "tool_error": "Command exited with code 1"}),
        ("Stop", {}),
        ("SessionEnd", {}),
    ]
    for name, extra in steps:
        fire(mode, make_payload(session_id, name, cwd, **extra))
        print(f"[{session_id[:8]}] sent {name}")
        time.sleep(hold if name == "PermissionRequest" else pace)


def run_multi(mode: str, count: int, pace: float) -> None:
    sessions = [
        (str(uuid.uuid4()), f"/tmp/fake-project-{i}")
        for i in range(count)
    ]
    for sid, cwd in sessions:
        fire(mode, make_payload(sid, "SessionStart", cwd))
        fire(mode, make_payload(sid, "UserPromptSubmit", cwd))
        print(f"[{sid[:8]}] spawned")
    events = ["PreToolUse", "PostToolUse", "PermissionRequest", "PostToolUseFailure", "Stop"]
    tools = ["Bash", "Read", "Edit", "Grep"]
    try:
        while True:
            sid, cwd = random.choice(sessions)
            name = random.choice(events)
            extra = {"tool_name": random.choice(tools)} if name in ("PreToolUse", "PostToolUseFailure") else {}
            fire(mode, make_payload(sid, name, cwd, **extra))
            print(f"[{sid[:8]}] sent {name}")
            time.sleep(pace)
    except KeyboardInterrupt:
        for sid, cwd in sessions:
            fire(mode, make_payload(sid, "SessionEnd", cwd))
        print("despawned all fake agents")


def run_crash(mode: str) -> None:
    session_id = str(uuid.uuid4())
    cwd = os.getcwd()
    proc = subprocess.Popen(["sleep", "5"])
    pid = proc.pid
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    session_path = SESSIONS_DIR / f"{pid}.json"
    session_path.write_text(json.dumps({
        "pid": pid,
        "sessionId": session_id,
        "cwd": cwd,
        "startedAt": int(time.time() * 1000),
        "procStart": time.ctime(),
        "version": "0.0.0-fake",
        "peerProtocol": 1,
        "kind": "interactive",
        "entrypoint": "cli",
        "name": "fake-crash-test",
        "nameSource": "derived",
    }))
    try:
        fire(mode, make_payload(session_id, "SessionStart", cwd))
        print(f"[{session_id[:8]}] registered with real pid {pid}; waiting for it to die "
              f"without SessionEnd (reaper should despawn within ~2-4s after)...")
        proc.wait()
        print(f"[{session_id[:8]}] fake process exited -- watch the daemon/frontend for despawn")
    finally:
        session_path.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--scenario", choices=["full-lifecycle", "multi", "crash"], default="full-lifecycle")
    parser.add_argument("--mode", choices=["via-emitter", "direct-udp"], default="direct-udp")
    parser.add_argument("--pace", type=float, default=1.0, help="Seconds between steps.")
    parser.add_argument("--hold", type=float, default=4.0, help="Seconds to hold at PermissionRequest.")
    parser.add_argument("--agents", type=int, default=3, help="Agent count for the multi scenario.")
    parser.add_argument("--session-id", default=None, help="Fixed session_id for full-lifecycle.")
    parser.add_argument("--cwd", default="/tmp/fake-project", help="Fake project directory.")
    args = parser.parse_args()

    if args.scenario == "full-lifecycle":
        run_full_lifecycle(args.mode, args.session_id or str(uuid.uuid4()), args.cwd, args.pace, args.hold)
    elif args.scenario == "multi":
        run_multi(args.mode, args.agents, args.pace)
    elif args.scenario == "crash":
        run_crash(args.mode)


if __name__ == "__main__":
    main()
