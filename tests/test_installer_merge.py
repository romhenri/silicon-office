import json
import pathlib

from silicon_office.common.constants import TARGET_HOOK_EVENTS
from silicon_office.installer.install_hooks import build_updated_settings, run

FIXTURE = json.loads(
    (pathlib.Path(__file__).parent / "fixtures" / "settings_json_sample.json").read_text()
)
EMITTER_PATH = "/Users/example/GameDev/silicon-office/.venv/bin/claude-vo-emit"


def _vibe_island_group(event: str) -> list:
    """The single pre-existing (non-ours) matcher-group for `event`, if any."""
    return [g for g in FIXTURE.get("hooks", {}).get(event, [])]


def test_install_adds_our_entry_to_every_target_event_without_removing_others():
    updated = build_updated_settings(FIXTURE, EMITTER_PATH, install=True)
    for event in TARGET_HOOK_EVENTS:
        groups = updated["hooks"][event]
        commands = [h["command"] for g in groups for h in g["hooks"]]
        assert EMITTER_PATH in commands
        # every pre-existing vibe-island group for this event must survive untouched
        for original_group in _vibe_island_group(event):
            assert original_group in groups


def test_install_does_not_touch_unrelated_top_level_keys():
    updated = build_updated_settings(FIXTURE, EMITTER_PATH, install=True)
    assert updated["env"] == FIXTURE["env"]
    assert updated["statusLine"] == FIXTURE["statusLine"]
    assert updated["tui"] == FIXTURE["tui"]


def test_install_does_not_touch_excluded_events():
    # PreCompact is deliberately excluded from TARGET_HOOK_EVENTS.
    updated = build_updated_settings(FIXTURE, EMITTER_PATH, install=True)
    assert updated["hooks"]["PreCompact"] == FIXTURE["hooks"]["PreCompact"]


def test_install_creates_missing_target_event_from_scratch():
    # PostToolUseFailure isn't in the fixture at all.
    assert "PostToolUseFailure" not in FIXTURE.get("hooks", {})
    updated = build_updated_settings(FIXTURE, EMITTER_PATH, install=True)
    groups = updated["hooks"]["PostToolUseFailure"]
    commands = [h["command"] for g in groups for h in g["hooks"]]
    assert commands == [EMITTER_PATH]


def test_double_install_is_idempotent():
    once = build_updated_settings(FIXTURE, EMITTER_PATH, install=True)
    twice = build_updated_settings(once, EMITTER_PATH, install=True)
    assert once == twice


def test_uninstall_restores_original_shape():
    installed = build_updated_settings(FIXTURE, EMITTER_PATH, install=True)
    uninstalled = build_updated_settings(installed, EMITTER_PATH, install=False)
    assert uninstalled == FIXTURE


def test_install_on_empty_settings_creates_minimal_skeleton():
    updated = build_updated_settings({}, EMITTER_PATH, install=True)
    for event in TARGET_HOOK_EVENTS:
        commands = [h["command"] for g in updated["hooks"][event] for h in g["hooks"]]
        assert commands == [EMITTER_PATH]


def test_run_writes_atomically_and_backs_up(tmp_path):
    project_root = tmp_path / "project"
    claude_dir = project_root / ".claude"
    claude_dir.mkdir(parents=True)
    settings_path = claude_dir / "settings.json"
    settings_path.write_text(json.dumps(FIXTURE))

    rc = run("project", project_root, EMITTER_PATH, dry_run=False, uninstall=False)
    assert rc == 0

    backups = list(claude_dir.glob("settings.json.backup.*"))
    assert len(backups) == 1
    assert json.loads(backups[0].read_text()) == FIXTURE

    written = json.loads(settings_path.read_text())
    commands = [h["command"] for g in written["hooks"]["PreToolUse"] for h in g["hooks"]]
    assert EMITTER_PATH in commands

    # running again should be a no-op: no second backup, file unchanged
    rc = run("project", project_root, EMITTER_PATH, dry_run=False, uninstall=False)
    assert rc == 0
    assert len(list(claude_dir.glob("settings.json.backup.*"))) == 1
    assert json.loads(settings_path.read_text()) == written


def test_run_dry_run_does_not_write(tmp_path):
    project_root = tmp_path / "project"
    claude_dir = project_root / ".claude"
    claude_dir.mkdir(parents=True)
    settings_path = claude_dir / "settings.json"
    settings_path.write_text(json.dumps(FIXTURE))

    run("project", project_root, EMITTER_PATH, dry_run=True, uninstall=False)

    assert json.loads(settings_path.read_text()) == FIXTURE
    assert not list(claude_dir.glob("settings.json.backup.*"))


def test_run_on_missing_settings_file_skips_backup(tmp_path):
    project_root = tmp_path / "project"
    rc = run("project", project_root, EMITTER_PATH, dry_run=False, uninstall=False)
    assert rc == 0
    claude_dir = project_root / ".claude"
    assert not list(claude_dir.glob("settings.json.backup.*"))
    written = json.loads((claude_dir / "settings.json").read_text())
    assert EMITTER_PATH in [
        h["command"] for g in written["hooks"]["PreToolUse"] for h in g["hooks"]
    ]
