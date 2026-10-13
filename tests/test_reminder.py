import sys
from collections.abc import Sequence
from pathlib import Path

import pytest
from conftest import (
    append_json_lines,
    home_environment,
    json_at,
    run_json_hook,
    text_at,
)
from json_values import JsonObject, JsonValue

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hooks"))

from rule_sections import RuleSection

from agents import AGENTS, Agent

ROOT = Path(__file__).resolve().parent.parent
REMINDER = ROOT / "hooks" / "reminder.py"
RULES = ROOT / "INSTRUCTIONS.md"
CLAUDE_ARGUMENTS = ["--harness", "claude"]
PARTS = 4


def reminder(
    home: Path,
    part: int,
    payload: JsonObject,
    arguments: Sequence[str] = CLAUDE_ARGUMENTS,
) -> JsonValue:
    return run_json_hook(
        REMINDER, payload, str(part), str(PARTS), *arguments, env=home_environment(home)
    )


def context(output: JsonValue) -> str | None:
    return (
        text_at(output, "hookSpecificOutput", "additionalContext") if output else None
    )


def all_parts(
    home: Path, payload: JsonObject, arguments: Sequence[str] = CLAUDE_ARGUMENTS
) -> list[str | None]:
    return [
        context(reminder(home, part, payload, arguments))
        for part in range(1, PARTS + 1)
    ]


def transcript_at(tmp_path: Path, tokens: int) -> Path:
    transcript = tmp_path / "transcript.jsonl"
    entry: JsonObject = {
        "type": "assistant",
        "message": {"model": "claude-opus-5-5", "usage": {"input_tokens": tokens}},
    }
    append_json_lines(transcript, entry)
    return transcript


def prompt(transcript: Path, prompt_id: str) -> JsonObject:
    return {
        "hook_event_name": "UserPromptSubmit",
        "session_id": "s1",
        "prompt_id": prompt_id,
        "transcript_path": str(transcript),
    }


def tool_batch(transcript: Path, prompt_id: str) -> JsonObject:
    return {**prompt(transcript, prompt_id), "hook_event_name": "PostToolBatch"}


def test_session_start_sends_the_whole_file_in_parts(home: Path) -> None:
    parts = all_parts(home, {"hook_event_name": "SessionStart", "session_id": "s1"})
    sent = [part for part in parts if part]
    headings = [
        line for line in RULES.read_text().splitlines() if line.startswith("# ")
    ]
    assert len(sent) == 2
    assert all(heading in "".join(sent) for heading in headings)
    assert all(len(part) <= 10_000 for part in sent)


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
def test_start_sends_the_file(home: Path, payload: JsonObject) -> None:
    assert context(reminder(home, 1, payload))


def rule_headings() -> list[str]:
    return [line for line in RULES.read_text().splitlines() if line.startswith("# ")]


def subagent_rules(home: Path, agent_type: str) -> str:
    payload = {
        "hook_event_name": "SubagentStart",
        "agent_id": "a1",
        "agent_type": agent_type,
    }
    return "".join(part for part in all_parts(home, payload) if part)


@pytest.mark.parametrize("agent", AGENTS, ids=lambda agent: agent.name)
def test_agents_get_only_their_sections(home: Path, agent: Agent) -> None:
    sent = subagent_rules(home, agent.name)
    for heading in rule_headings():
        assert (heading in sent) == (heading.removeprefix("# ") in agent.rule_sections)


def test_rule_sections_match_headings() -> None:
    headings = [
        line for line in RULES.read_text().splitlines() if line.startswith("# ")
    ]
    assert [f"# {section}" for section in RuleSection] == headings


def test_agents_name_real_agent_files() -> None:
    agents = ROOT / "agents"
    names = {
        line.removeprefix("name: ")
        for path in agents.glob("*.md")
        for line in path.read_text().splitlines()
        if line.startswith("name: ")
    }
    assert {agent.name.removeprefix("misticos:") for agent in AGENTS} == names


def test_other_subagents_get_every_section(home: Path) -> None:
    sent = subagent_rules(home, "general-purpose")
    assert all(heading in sent for heading in rule_headings())


@pytest.mark.parametrize(
    "agent",
    [agent for agent in AGENTS if not agent.rule_sections],
    ids=lambda agent: agent.name,
)
@pytest.mark.parametrize("ids", [{"agent_id": "a1"}, {}], ids=["with-id", "without-id"])
def test_agents_without_sections_get_nothing(
    home: Path, agent: Agent, ids: JsonObject
) -> None:
    payload = {"hook_event_name": "SubagentStart", "agent_type": agent.name, **ids}
    assert all_parts(home, payload) == [None] * PARTS


def test_growth_sends_a_pointer_then_a_full_copy(home: Path, tmp_path: Path) -> None:
    transcript = transcript_at(tmp_path, 10_000)
    assert all_parts(home, prompt(transcript, "p1")) == [None] * PARTS
    transcript_at(tmp_path, 40_000)
    pointer = all_parts(home, tool_batch(transcript, "p2"))
    assert pointer[0] and pointer[1:] == [None] * (PARTS - 1)
    transcript_at(tmp_path, 45_000)
    assert all_parts(home, prompt(transcript, "p3")) == [None] * PARTS
    transcript_at(tmp_path, 120_000)
    copy = all_parts(home, prompt(transcript, "p4"))
    assert copy[0] and copy[1]
    assert len(copy[0]) > len(pointer[0])


def test_subagent_growth_gets_nothing(home: Path, tmp_path: Path) -> None:
    transcript = transcript_at(tmp_path, 500_000)
    payload: JsonObject = {**prompt(transcript, "p1"), "agent_id": "a1"}
    assert all_parts(home, payload) == [None] * PARTS


def test_cursor_shape(home: Path) -> None:
    cursor = ["--harness", "cursor"]
    payload: JsonObject = {"hook_event_name": "sessionStart", "session_id": "c1"}
    output = reminder(home, 1, payload, cursor)
    assert json_at(output, "additional_context")


def test_session_start_with_a_non_text_session_id_still_sends_the_rules(
    home: Path,
) -> None:
    payload: JsonObject = {"hook_event_name": "SessionStart", "session_id": 1}
    assert context(reminder(home, 1, payload))


def test_prompt_without_a_token_count_gets_nothing(home: Path, tmp_path: Path) -> None:
    missing = tmp_path / "missing.jsonl"
    assert all_parts(home, prompt(missing, "p1")) == [None] * PARTS


def test_a_prompt_gets_the_copy_but_not_the_pointer(home: Path, tmp_path: Path) -> None:
    transcript = transcript_at(tmp_path, 10_000)
    assert all_parts(home, prompt(transcript, "p1")) == [None] * PARTS
    transcript_at(tmp_path, 40_000)
    assert all_parts(home, prompt(transcript, "p2")) == [None] * PARTS
    transcript_at(tmp_path, 120_000)
    copy = all_parts(home, prompt(transcript, "p3"))
    assert copy[0] and copy[1]
