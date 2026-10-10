import json
import subprocess
import sys
from pathlib import Path

import pytest

REMINDER = Path(__file__).resolve().parent.parent / "hooks" / "reminder.py"
CLAUDE_ARGUMENTS = ["--harness", "claude"]
PARTS = 4


@pytest.fixture
def home(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    return home


def reminder(home, part, payload, arguments=CLAUDE_ARGUMENTS):
    result = subprocess.run(
        [sys.executable, str(REMINDER), str(part), str(PARTS), *arguments],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env={"HOME": str(home), "PATH": "/usr/bin:/bin"},
        check=True,
    )
    return json.loads(result.stdout) if result.stdout else None


def context(output):
    return output["hookSpecificOutput"]["additionalContext"] if output else None


def all_parts(home, payload, arguments=CLAUDE_ARGUMENTS):
    return [
        context(reminder(home, part, payload, arguments))
        for part in range(1, PARTS + 1)
    ]


def transcript_at(tmp_path, tokens):
    transcript = tmp_path / "transcript.jsonl"
    entry = {
        "type": "assistant",
        "message": {"model": "claude-opus-5-5", "usage": {"input_tokens": tokens}},
    }
    with transcript.open("a") as lines:
        lines.write(json.dumps(entry) + "\n")
    return transcript


def prompt(transcript, prompt_id):
    return {
        "hook_event_name": "UserPromptSubmit",
        "session_id": "s1",
        "prompt_id": prompt_id,
        "transcript_path": str(transcript),
    }


def test_session_start_sends_the_whole_file_in_parts(home):
    parts = all_parts(home, {"hook_event_name": "SessionStart", "session_id": "s1"})
    sent = [part for part in parts if part]
    assert len(sent) == 2
    assert sent[0].startswith("INSTRUCTIONS.md holds the standing rules")
    assert "part 2 of 2" in sent[1]
    assert "# Communication" in "".join(sent)
    assert all(len(part) <= 10_000 for part in sent)


def test_model_tiers_are_named(home):
    parts = all_parts(home, {"hook_event_name": "SessionStart", "session_id": "s1"})
    text = "".join(part for part in parts if part)
    assert "Give Haiku work" in text
    assert "the cheap model" not in text


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param(
            {"hook_event_name": "SubagentStart", "agent_id": "a1", "agent_type": "x"},
            id="subagent",
        ),
        pytest.param(
            {
                "hook_event_name": "SessionStart",
                "session_id": "s1",
                "agent_type": "misticos:scout",
            },
            id="main-session-of-a-skipped-type",
        ),
    ],
)
def test_start_sends_the_file(home, payload):
    assert context(reminder(home, 1, payload)).startswith("INSTRUCTIONS.md holds")


def test_skipped_agent_types_get_nothing(home):
    payload = {
        "hook_event_name": "SubagentStart",
        "agent_id": "a1",
        "agent_type": "misticos:scout",
    }
    assert all_parts(home, payload) == [None] * PARTS


def test_growth_sends_a_pointer_then_a_full_copy(home, tmp_path):
    transcript = transcript_at(tmp_path, 10_000)
    assert all_parts(home, prompt(transcript, "p1")) == [None] * PARTS
    transcript_at(tmp_path, 40_000)
    pointer = all_parts(home, prompt(transcript, "p2"))
    assert pointer[0].startswith("INSTRUCTIONS.md holds the standing rules")
    assert "read " in pointer[0] and pointer[1:] == [None] * (PARTS - 1)
    transcript_at(tmp_path, 45_000)
    assert all_parts(home, prompt(transcript, "p3")) == [None] * PARTS
    transcript_at(tmp_path, 120_000)
    copy = all_parts(home, prompt(transcript, "p4"))
    assert copy[0].startswith("The conversation has grown")
    assert copy[1].startswith("INSTRUCTIONS.md continues here, part 2 of 2")


def test_subagent_growth_gets_nothing(home, tmp_path):
    transcript = transcript_at(tmp_path, 500_000)
    payload = {**prompt(transcript, "p1"), "agent_id": "a1"}
    assert all_parts(home, payload) == [None] * PARTS


def test_cursor_shape(home):
    cursor = ["--harness", "cursor"]
    payload = {"hook_event_name": "sessionStart", "conversation_id": "c1"}
    output = reminder(home, 1, payload, cursor)
    assert output["additional_context"].startswith("INSTRUCTIONS.md holds")
