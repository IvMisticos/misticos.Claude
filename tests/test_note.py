from pathlib import Path

import pytest
from conftest import home_environment, run_json_hook

NOTE = Path(__file__).resolve().parent.parent / "hooks" / "note.py"


def call_note(home, name, session_id, agent_id=None):
    payload = {"hook_event_name": "PostToolUse", "session_id": session_id}
    if agent_id:
        payload["agent_id"] = agent_id
    return run_json_hook(NOTE, payload, name, env=home_environment(home))


def noted_calls(home, name, session_id, calls):
    return [call_note(home, name, session_id) is not None for _ in range(calls)]


def test_notifications_note_comes_on_every_fifth_call(tmp_path):
    noted = noted_calls(tmp_path, "notifications", "s1", 11)
    assert [number for number, due in enumerate(noted, 1) if due] == [1, 6, 11]


def test_notifications_count_is_per_session(tmp_path):
    noted_calls(tmp_path, "notifications", "s1", 2)
    assert call_note(tmp_path, "notifications", "s2") is not None
    assert call_note(tmp_path, "notifications", "s1") is None


def test_notifications_count_is_per_agent_within_a_session(tmp_path):
    noted_calls(tmp_path, "notifications", "s1", 2)
    assert call_note(tmp_path, "notifications", "s1", "a1") is not None
    assert call_note(tmp_path, "notifications", "s1", "a1") is None
    assert call_note(tmp_path, "notifications", "s1", "a2") is not None
    assert call_note(tmp_path, "notifications", "s1") is None


@pytest.mark.parametrize("name", ["agent-roles", "pr-body"])
def test_other_notes_come_on_every_call(tmp_path, name):
    assert all(noted_calls(tmp_path, name, "s1", 3))
