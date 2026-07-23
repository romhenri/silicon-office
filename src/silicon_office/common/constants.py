"""Shared constants for the Silicon Office IPC pipeline."""

import os

UDP_HOST = "127.0.0.1"
UDP_PORT = int(os.environ.get("CLAUDE_VO_UDP_PORT", "51245"))

TCP_HOST = "127.0.0.1"
TCP_PORT = int(os.environ.get("CLAUDE_VO_TCP_PORT", "51246"))

# Marker embedded in the installed hook command so the installer can find,
# upgrade, or uninstall its own entries without disturbing anyone else's.
HOOK_MARKER = "claude-vo-emit"

# Hook events this system listens to. Deliberately excludes Notification and
# PreCompact (present on some machines' existing hook configs) to keep the
# footprint minimal per RNF-01.
TARGET_HOOK_EVENTS = [
    "SessionStart",
    "SessionEnd",
    "UserPromptSubmit",
    "PreToolUse",
    "PostToolUse",
    "PostToolUseFailure",
    "PermissionRequest",
    "Stop",
    "StopFailure",
    "SubagentStart",
    "SubagentStop",
]

SNAPSHOT_INTERVAL_SECONDS = 5.0
REAPER_INTERVAL_SECONDS = 2.0

STATE_IDLE = "idle"
STATE_WORKING = "working"
STATE_ASKING = "asking"
STATE_ERROR = "error"
