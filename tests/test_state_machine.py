from silicon_office.common.constants import (
    STATE_ASKING,
    STATE_ERROR,
    STATE_IDLE,
    STATE_WORKING,
)
from silicon_office.common.schema import HookEvent
from silicon_office.daemon.state_machine import apply_event


def _event(session_id="s1", name="SessionStart", **kw) -> HookEvent:
    return HookEvent(session_id=session_id, hook_event_name=name, cwd="/tmp/proj", **kw)


def test_session_start_creates_idle_record():
    record, op = apply_event(None, _event(name="SessionStart"), now=1.0)
    assert op == "upsert"
    assert record.state == STATE_IDLE
    assert record.project_name == "proj"


def test_user_prompt_submit_goes_working():
    record, _ = apply_event(None, _event(name="SessionStart"), now=1.0)
    record, op = apply_event(record, _event(name="UserPromptSubmit"), now=2.0)
    assert op == "upsert"
    assert record.state == STATE_WORKING
    assert record.state_since == 2.0


def test_pre_tool_use_labels_bash():
    record, _ = apply_event(None, _event(name="SessionStart"), now=1.0)
    record, _ = apply_event(record, _event(name="PreToolUse", tool_name="Bash"), now=2.0)
    assert record.state == STATE_WORKING
    assert record.action_label == "Bash Execution"


def test_pre_tool_use_unknown_tool_falls_back():
    record, _ = apply_event(None, _event(name="SessionStart"), now=1.0)
    record, _ = apply_event(record, _event(name="PreToolUse", tool_name="Frobnicate"), now=2.0)
    assert record.action_label == "Using Frobnicate"


def test_post_tool_use_does_not_reset_state_since_if_already_working():
    record, _ = apply_event(None, _event(name="SessionStart"), now=1.0)
    record, _ = apply_event(record, _event(name="PreToolUse", tool_name="Bash"), now=2.0)
    record, op = apply_event(record, _event(name="PostToolUse", tool_name="Bash"), now=3.0)
    assert op == "upsert"
    assert record.state == STATE_WORKING
    assert record.state_since == 2.0  # unchanged, still mid-turn


def test_permission_request_triggers_asking():
    record, _ = apply_event(None, _event(name="SessionStart"), now=1.0)
    record, op = apply_event(record, _event(name="PermissionRequest", tool_name="Bash"), now=2.0)
    assert op == "upsert"
    assert record.state == STATE_ASKING
    assert "Bash" in record.action_label


def test_post_tool_use_failure_triggers_error():
    record, _ = apply_event(None, _event(name="SessionStart"), now=1.0)
    record, op = apply_event(record, _event(name="PostToolUseFailure", tool_name="Bash"), now=2.0)
    assert op == "upsert"
    assert record.state == STATE_ERROR


def test_stop_failure_triggers_error():
    record, _ = apply_event(None, _event(name="SessionStart"), now=1.0)
    record, op = apply_event(record, _event(name="StopFailure"), now=2.0)
    assert record.state == STATE_ERROR


def test_stop_returns_to_idle():
    record, _ = apply_event(None, _event(name="SessionStart"), now=1.0)
    record, _ = apply_event(record, _event(name="PreToolUse", tool_name="Bash"), now=2.0)
    record, op = apply_event(record, _event(name="Stop"), now=3.0)
    assert op == "upsert"
    assert record.state == STATE_IDLE


def test_session_end_removes():
    record, _ = apply_event(None, _event(name="SessionStart"), now=1.0)
    record, op = apply_event(record, _event(name="SessionEnd"), now=2.0)
    assert op == "remove"
    assert record is None


def test_unseen_session_auto_creates_even_on_unmapped_event():
    record, op = apply_event(None, _event(name="SomeFutureHookEvent"), now=1.0)
    assert op == "upsert"
    assert record is not None
    assert record.state == STATE_IDLE


def test_unmapped_event_on_known_session_is_noop():
    record, _ = apply_event(None, _event(name="SessionStart"), now=1.0)
    before = (record.state, record.action_label, record.state_since)
    record, op = apply_event(record, _event(name="SomeFutureHookEvent"), now=99.0)
    assert op == "noop"
    assert (record.state, record.action_label, record.state_since) == before


def test_subagent_label_stack_push_and_restore():
    record, _ = apply_event(None, _event(name="SessionStart"), now=1.0)
    record, _ = apply_event(record, _event(name="PreToolUse", tool_name="Bash"), now=2.0)
    prior_label = record.action_label
    record, op = apply_event(
        record, _event(name="SubagentStart", agent_type="Explore"), now=3.0
    )
    assert op == "upsert"
    assert "Explore" in record.action_label
    assert record.label_stack == [prior_label]

    record, op = apply_event(record, _event(name="SubagentStop"), now=4.0)
    assert op == "upsert"
    assert record.action_label == prior_label
    assert record.label_stack == []


def test_subagent_stop_without_prior_start_does_not_crash():
    record, _ = apply_event(None, _event(name="SessionStart"), now=1.0)
    record, op = apply_event(record, _event(name="SubagentStop"), now=2.0)
    assert op == "upsert"
    assert record.action_label == "Working"
