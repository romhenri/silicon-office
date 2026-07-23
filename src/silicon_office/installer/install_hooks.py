"""Idempotent installer that merges Silicon Office's observer hook
into a Claude Code settings.json, without disturbing anyone else's hooks.

Defaults to the *project-local* .claude/settings.json -- this MVP
deliberately does not touch the global ~/.claude/settings.json, which may
already have other hooks wired in (e.g. a third-party bridge tool). Pass
--scope global to promote to the global file once the pipeline is validated;
the merge algorithm is scope-agnostic and safe either way.
"""

from __future__ import annotations

import argparse
import copy
import datetime
import json
import os
import pathlib
import shutil
import sys
from typing import Any, Optional

from silicon_office.common.constants import HOOK_MARKER, TARGET_HOOK_EVENTS


def _default_emitter_path() -> str:
    return os.path.join(os.path.dirname(sys.executable), "claude-vo-emit")


def _settings_path(scope: str, project_root: pathlib.Path) -> pathlib.Path:
    if scope == "global":
        return pathlib.Path.home() / ".claude" / "settings.json"
    return project_root / ".claude" / "settings.json"


def _load(path: pathlib.Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise SystemExit(
            f"Refusing to touch {path}: existing file is not valid JSON ({exc})"
        )


def _is_ours(hook_entry: dict[str, Any]) -> bool:
    return HOOK_MARKER in str(hook_entry.get("command", ""))


def _strip_ours(matcher_groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop any matcher-group entries that are ours, preserving everyone
    else's groups (and their order) untouched."""
    kept = []
    for group in matcher_groups:
        remaining = [h for h in group.get("hooks", []) if not _is_ours(h)]
        if remaining:
            new_group = dict(group)
            new_group["hooks"] = remaining
            kept.append(new_group)
        # else: group was entirely ours -- drop it
    return kept


def _our_group(emitter_path: str) -> dict[str, Any]:
    return {"hooks": [{"type": "command", "command": emitter_path, "async": True}]}


def build_updated_settings(
    settings: dict[str, Any], emitter_path: str, install: bool
) -> dict[str, Any]:
    """Returns a new settings dict with our hook entries merged in (install)
    or removed (uninstall). Never mutates unrelated top-level keys or other
    tools' matcher-groups -- only claude-vo-emit-marked entries are touched."""
    updated = copy.deepcopy(settings)
    hooks = updated.setdefault("hooks", {})
    for event in TARGET_HOOK_EVENTS:
        groups = _strip_ours(hooks.get(event, []))
        if install:
            groups = groups + [_our_group(emitter_path)]
        if groups:
            hooks[event] = groups
        elif event in hooks:
            del hooks[event]
    if not hooks:
        updated.pop("hooks", None)
    return updated


def _backup(path: pathlib.Path) -> None:
    if not path.exists():
        return
    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    backup_path = path.with_name(f"{path.name}.backup.{ts}")
    shutil.copy2(path, backup_path)


def _atomic_write(path: pathlib.Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    os.replace(tmp, path)


def run(
    scope: str,
    project_root: pathlib.Path,
    emitter_path: str,
    dry_run: bool,
    uninstall: bool,
) -> int:
    path = _settings_path(scope, project_root)
    existing = _load(path)
    updated = build_updated_settings(existing, emitter_path, install=not uninstall)

    if updated == existing:
        print(f"{path}: already up to date, nothing to do.")
        return 0

    if dry_run:
        action = "uninstall" if uninstall else "install"
        print(f"Would {action} hooks in {path}:")
        print(json.dumps(updated, indent=2))
        return 0

    _backup(path)
    _atomic_write(path, updated)
    verb = "Uninstalled" if uninstall else "Installed"
    print(f"{verb} hooks in {path}")
    return 0


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scope",
        choices=["project", "global"],
        default="project",
        help="Install into the project-local .claude/settings.json (default) "
        "or the global ~/.claude/settings.json.",
    )
    parser.add_argument(
        "--project-root",
        default=".",
        help="Project root when --scope=project (default: current directory).",
    )
    parser.add_argument(
        "--emitter-path",
        default=None,
        help="Absolute path to the claude-vo-emit console script "
        "(default: inferred from the running interpreter's venv).",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--uninstall", action="store_true")
    return parser.parse_args(argv)


def main() -> None:
    args = parse_args()
    emitter_path = args.emitter_path or _default_emitter_path()
    project_root = pathlib.Path(args.project_root).resolve()
    raise SystemExit(
        run(args.scope, project_root, emitter_path, args.dry_run, args.uninstall)
    )


if __name__ == "__main__":
    main()
