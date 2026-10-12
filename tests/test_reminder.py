import json
import sys
from pathlib import Path

import pytest
from conftest import home_environment, run_json_hook

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hooks"))

from rule_sections import RuleSection

from agents import AGENTS

ROOT = Path(__file__).resolve().parent.parent
REMINDER = ROOT / "hooks" / "reminder.py"
RULES = ROOT / "INSTRUCTIONS.md"
CLAUDE_ARGUMENTS = ["--harness", "claude"]
PARTS = 4


def reminder(home, part, payload, arguments=CLAUDE_ARGUMENTS):
    return run_json_hook(
        REMINDER, payload, str(part), str(PARTS), *arguments, env=home_environment(home)
    )


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
def test_start_sends_the_file(home, payload):
    assert context(reminder(home, 1, payload))


def rule_headings():
    return [line for line in RULES.read_text().splitlines() if line.startswith("# ")]


def subagent_rules(home, agent_type):
    payload = {
        "hook_event_name": "SubagentStart",
        "agent_id": "a1",
        "agent_type": agent_type,
    }
    return "".join(part for part in all_parts(home, payload) if part)


@pytest.mark.parametrize("agent", AGENTS, ids=lambda agent: agent.name)
def test_agents_get_only_their_sections(home, agent):
    sent = subagent_rules(home, agent.name)
    for heading in rule_headings():
        assert (heading in sent) == (heading.removeprefix("# ") in agent.rule_sections)


def test_rule_sections_match_headings():
    headings = [
        line for line in RULES.read_text().splitlines() if line.startswith("# ")
    ]
    assert [f"# {section}" for section in RuleSection] == headings


def test_agents_name_real_agent_files():
    agents = ROOT / "agents"
    names = {
        line.removeprefix("name: ")
        for path in agents.glob("*.md")
        for line in path.read_text().splitlines()
        if line.startswith("name: ")
    }
    assert {agent.name.removeprefix("misticos:") for agent in AGENTS} == names


def test_other_subagents_get_every_section(home):
    sent = subagent_rules(home, "general-purpose")
    assert all(heading in sent for heading in rule_headings())


@pytest.mark.parametrize(
    "agent",
    [agent for agent in AGENTS if not agent.rule_sections],
    ids=lambda agent: agent.name,
)
@pytest.mark.parametrize("ids", [{"agent_id": "a1"}, {}], ids=["with-id", "without-id"])
def test_agents_without_sections_get_nothing(home, agent, ids):
    payload = {"hook_event_name": "SubagentStart", "agent_type": agent.name, **ids}
    assert all_parts(home, payload) == [None] * PARTS


def test_growth_sends_a_pointer_then_a_full_copy(home, tmp_path):
    transcript = transcript_at(tmp_path, 10_000)
    assert all_parts(home, prompt(transcript, "p1")) == [None] * PARTS
    transcript_at(tmp_path, 40_000)
    pointer = all_parts(home, prompt(transcript, "p2"))
    assert pointer[0] and pointer[1:] == [None] * (PARTS - 1)
    transcript_at(tmp_path, 45_000)
    assert all_parts(home, prompt(transcript, "p3")) == [None] * PARTS
    transcript_at(tmp_path, 120_000)
    copy = all_parts(home, prompt(transcript, "p4"))
    assert len(copy[0]) > len(pointer[0]) and copy[1]


def test_subagent_growth_gets_nothing(home, tmp_path):
    transcript = transcript_at(tmp_path, 500_000)
    payload = {**prompt(transcript, "p1"), "agent_id": "a1"}
    assert all_parts(home, payload) == [None] * PARTS


def test_cursor_shape(home):
    cursor = ["--harness", "cursor"]
    payload = {"hook_event_name": "sessionStart", "conversation_id": "c1"}
    output = reminder(home, 1, payload, cursor)
    assert output["additional_context"]
