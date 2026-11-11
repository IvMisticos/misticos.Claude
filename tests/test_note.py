from pathlib import Path

import pytest
from conftest import home_environment, run_json_hook
from json_values import JsonValue

NOTE = Path(__file__).resolve().parent.parent / "hooks" / "note.py"


def call_note(
    home: Path, name: str, session_id: str, agent_id: str | None = None
) -> JsonValue:
    payload = {"hook_event_name": "PostToolUse", "session_id": session_id}
    if agent_id:
        payload["agent_id"] = agent_id
    return run_json_hook(NOTE, payload, name, env=home_environment(home))


def noted_calls(home: Path, name: str, session_id: str, calls: int) -> list[bool]:
    return [call_note(home, name, session_id) is not None for _ in range(calls)]


@pytest.mark.parametrize("name", ["agent-roles", "pr-body"])
def test_other_notes_come_on_every_call(tmp_path: Path, name: str) -> None:
    assert all(noted_calls(tmp_path, name, "s1", 3))
