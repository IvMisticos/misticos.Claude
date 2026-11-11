import json
from collections.abc import Sequence
from pathlib import Path

import pytest
from conftest import (
    append_json_lines,
    home_environment,
    hook_commands,
    json_at,
    plugin_hook_command,
    run_json_hook,
    text_at,
)
from json_values import JsonObject, JsonValue
from reminder import REMINDER_PARTS
from rule_sections import RuleSection
from transcript import CHARS_PER_TOKEN_ESTIMATE

from agents import AGENTS, Agent

ROOT = Path(__file__).resolve().parent.parent
REMINDER = ROOT / "hooks" / "reminder.py"
RULES = ROOT / "INSTRUCTIONS.md"
CLAUDE_ARGUMENTS = ["--harness", "claude"]
CURSOR_ARGUMENTS = ["--harness", "cursor"]
CODEX_ARGUMENTS = ["--harness", "codex"]


def reminder(
    home: Path,
    part: int,
    payload: JsonObject,
    arguments: Sequence[str] = CLAUDE_ARGUMENTS,
) -> JsonValue:
    return run_json_hook(
        REMINDER, payload, str(part), *arguments, env=home_environment(home)
    )


def context(output: JsonValue) -> str | None:
    match output:
        case None:
            return None
        case {"additional_context": str(cursor_context)}:
            return cursor_context
        case _:
            return text_at(output, "hookSpecificOutput", "additionalContext")


def all_parts(
    home: Path, payload: JsonObject, arguments: Sequence[str] = CLAUDE_ARGUMENTS
) -> list[str | None]:
    return [
        context(reminder(home, part, payload, arguments))
        for part in range(1, REMINDER_PARTS + 1)
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


def tool_batch(transcript: Path, prompt_id: str, tool_use_id: str) -> JsonObject:
    return {
        **prompt(transcript, prompt_id),
        "hook_event_name": "PostToolBatch",
        "tool_calls": [{"tool_use_id": tool_use_id}],
    }


def rule_headings() -> list[str]:
    return [line for line in RULES.read_text().splitlines() if line.startswith("# ")]


def test_session_start_sends_the_whole_file_in_parts(home: Path) -> None:
    parts = all_parts(home, {"hook_event_name": "SessionStart", "session_id": "s1"})
    sent = [part for part in parts if part]
    assert len(sent) > 1
    assert all(heading in "".join(sent) for heading in rule_headings())
    assert all(len(part) <= 10_000 for part in sent)


def session_start(session_id: str, source: str) -> JsonObject:
    return {
        "hook_event_name": "SessionStart",
        "session_id": session_id,
        "source": source,
    }


def full_copy(home: Path) -> list[str | None]:
    return all_parts(home, session_start("fresh", "startup"))


def start_with_copy(home: Path, transcript: Path) -> None:
    assert all_parts(home, session_start("s1", "startup")) == full_copy(home)
    assert all_parts(home, prompt(transcript, "p1")) == [None] * REMINDER_PARTS


def outdated_receipt(home: Path, session_id: str) -> None:
    receipt = home / ".claude/hooks/data/misticos.Claude/rules-receipts" / session_id
    receipt.write_text(json.dumps({"digest": "digest of older rules"}))


@pytest.mark.parametrize("source", ["startup", "clear", "compact"])
def test_a_session_start_with_a_new_context_gets_the_copy_again(
    home: Path, tmp_path: Path, source: str
) -> None:
    start_with_copy(home, transcript_at(tmp_path, 10_000))
    assert all_parts(home, session_start("s1", source)) == full_copy(home)


def test_a_resume_with_unchanged_rules_keeps_the_copy_and_growth_baseline(
    home: Path, tmp_path: Path
) -> None:
    transcript = transcript_at(tmp_path, 10_000)
    start_with_copy(home, transcript)
    assert all_parts(home, session_start("s1", "resume")) == [None] * REMINDER_PARTS
    transcript_at(tmp_path, 120_000)
    copy = all_parts(home, prompt(transcript, "p2"))
    assert copy[0] and copy[1]


def test_a_resume_after_a_growth_copy_keeps_that_copy(
    home: Path, tmp_path: Path
) -> None:
    transcript = transcript_at(tmp_path, 10_000)
    assert all_parts(home, prompt(transcript, "p1")) == [None] * REMINDER_PARTS
    transcript_at(tmp_path, 120_000)
    assert all_parts(home, prompt(transcript, "p2"))[0]
    assert all_parts(home, session_start("s1", "resume")) == [None] * REMINDER_PARTS


def test_a_fork_gets_the_copy(home: Path, tmp_path: Path) -> None:
    start_with_copy(home, transcript_at(tmp_path, 10_000))
    assert all_parts(home, session_start("s2", "fork")) == full_copy(home)


def test_a_resume_with_changed_rules_gets_the_copy(home: Path, tmp_path: Path) -> None:
    start_with_copy(home, transcript_at(tmp_path, 10_000))
    outdated_receipt(home, "s1")
    assert all_parts(home, session_start("s1", "resume")) == full_copy(home)


def test_a_resume_without_stored_state_gets_the_copy(home: Path) -> None:
    assert all_parts(home, session_start("s1", "resume")) == full_copy(home)


def test_a_resume_after_a_compaction_keeps_the_compaction_copy(home: Path) -> None:
    assert all_parts(home, session_start("s1", "startup")) == full_copy(home)
    outdated_receipt(home, "s1")
    assert all_parts(home, session_start("s1", "compact")) == full_copy(home)
    assert all_parts(home, session_start("s1", "resume")) == [None] * REMINDER_PARTS


def test_a_main_session_of_a_skipped_type_gets_the_file(home: Path) -> None:
    payload: JsonObject = {
        "hook_event_name": "SessionStart",
        "session_id": "s1",
        "agent_type": "misticos:scout",
    }
    assert context(reminder(home, 1, payload))


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
    assert [f"# {section}" for section in RuleSection] == rule_headings()


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
    assert all_parts(home, payload) == [None] * REMINDER_PARTS


def test_growth_sends_a_pointer_then_a_full_copy(home: Path, tmp_path: Path) -> None:
    transcript = transcript_at(tmp_path, 10_000)
    assert all_parts(home, prompt(transcript, "p1")) == [None] * REMINDER_PARTS
    transcript_at(tmp_path, 40_000)
    pointer = all_parts(home, tool_batch(transcript, "p1", "u1"))
    assert pointer[0] and pointer[1:] == [None] * (REMINDER_PARTS - 1)
    transcript_at(tmp_path, 45_000)
    assert all_parts(home, prompt(transcript, "p2")) == [None] * REMINDER_PARTS
    transcript_at(tmp_path, 120_000)
    copy = all_parts(home, prompt(transcript, "p3"))
    assert copy[0] and copy[1]
    assert len(copy[0]) > len(pointer[0])


def test_a_prompt_leaves_the_pointer_to_the_next_tool_batch(
    home: Path, tmp_path: Path
) -> None:
    transcript = transcript_at(tmp_path, 10_000)
    assert all_parts(home, prompt(transcript, "p1")) == [None] * REMINDER_PARTS
    transcript_at(tmp_path, 40_000)
    assert all_parts(home, prompt(transcript, "p2")) == [None] * REMINDER_PARTS
    transcript_at(tmp_path, 45_000)
    pointer = all_parts(home, tool_batch(transcript, "p2", "u1"))
    assert pointer[0] and pointer[1:] == [None] * (REMINDER_PARTS - 1)
    transcript_at(tmp_path, 60_000)
    later = all_parts(home, tool_batch(transcript, "p2", "u2"))
    assert later == [None] * REMINDER_PARTS


def codex_transcript_at(tmp_path: Path, tokens: int) -> Path:
    transcript = tmp_path / "rollout.jsonl"
    transcript.write_text("x" * tokens * CHARS_PER_TOKEN_ESTIMATE)
    return transcript


def codex_prompt(transcript: Path, turn_id: str) -> JsonObject:
    return {
        "hook_event_name": "UserPromptSubmit",
        "session_id": "x1",
        "turn_id": turn_id,
        "transcript_path": str(transcript),
    }


def codex_tool_use(transcript: Path, turn_id: str, tool_use_id: str) -> JsonObject:
    return {
        **codex_prompt(transcript, turn_id),
        "hook_event_name": "PostToolUse",
        "tool_use_id": tool_use_id,
    }


def test_a_codex_prompt_leaves_the_pointer_to_the_next_tool_use(
    home: Path, tmp_path: Path
) -> None:
    transcript = codex_transcript_at(tmp_path, 10_000)
    first = all_parts(home, codex_prompt(transcript, "t1"), CODEX_ARGUMENTS)
    assert first == [None] * REMINDER_PARTS
    codex_transcript_at(tmp_path, 40_000)
    second = all_parts(home, codex_prompt(transcript, "t2"), CODEX_ARGUMENTS)
    assert second == [None] * REMINDER_PARTS
    codex_transcript_at(tmp_path, 45_000)
    pointer = all_parts(home, codex_tool_use(transcript, "t2", "u1"), CODEX_ARGUMENTS)
    assert pointer[0] and pointer[1:] == [None] * (REMINDER_PARTS - 1)


def test_subagent_growth_gets_nothing(home: Path, tmp_path: Path) -> None:
    transcript = transcript_at(tmp_path, 500_000)
    payload: JsonObject = {**prompt(transcript, "p1"), "agent_id": "a1"}
    assert all_parts(home, payload) == [None] * REMINDER_PARTS


def test_cursor_shape(home: Path) -> None:
    payload: JsonObject = {"hook_event_name": "sessionStart", "session_id": "c1"}
    output = reminder(home, 1, payload, CURSOR_ARGUMENTS)
    assert json_at(output, "additional_context")


def cursor_tool_use(tool_use_id: str, tokens: int) -> JsonObject:
    return {
        "hook_event_name": "postToolUse",
        "conversation_id": "c1",
        "tool_use_id": tool_use_id,
        "tool_output": "x" * tokens * CHARS_PER_TOKEN_ESTIMATE,
    }


def test_cursor_counts_each_tool_output_once(home: Path) -> None:
    first = all_parts(home, cursor_tool_use("t1", 10_000), CURSOR_ARGUMENTS)
    assert first == [None] * REMINDER_PARTS
    second = all_parts(home, cursor_tool_use("t2", 20_000), CURSOR_ARGUMENTS)
    assert second == [None] * REMINDER_PARTS
    pointer = all_parts(home, cursor_tool_use("t3", 10_000), CURSOR_ARGUMENTS)
    assert pointer[0] and pointer[1:] == [None] * (REMINDER_PARTS - 1)


def test_session_start_with_a_non_text_session_id_still_sends_the_rules(
    home: Path,
) -> None:
    payload: JsonObject = {"hook_event_name": "SessionStart", "session_id": 1}
    assert context(reminder(home, 1, payload))


def test_prompt_without_a_token_count_gets_nothing(home: Path, tmp_path: Path) -> None:
    missing = tmp_path / "missing.jsonl"
    assert all_parts(home, prompt(missing, "p1")) == [None] * REMINDER_PARTS


def test_a_prompt_gets_the_copy(home: Path, tmp_path: Path) -> None:
    transcript = transcript_at(tmp_path, 10_000)
    assert all_parts(home, prompt(transcript, "p1")) == [None] * REMINDER_PARTS
    transcript_at(tmp_path, 120_000)
    copy = all_parts(home, prompt(transcript, "p2"))
    assert copy[0] and copy[1]


@pytest.mark.parametrize(
    ("config", "run", "harness"),
    [
        ("claude.json", plugin_hook_command("reminder.py"), ""),
        ("codex.json", plugin_hook_command("reminder.py"), " --harness codex"),
        (
            "cursor.json",
            '"${CURSOR_PLUGIN_ROOT}/hooks/run.sh" reminder.py',
            " --harness cursor",
        ),
    ],
    ids=("claude", "codex", "cursor"),
)
def test_every_reminder_event_runs_each_part_once(
    config: str, run: str, harness: str
) -> None:
    expected = [f"{run} {part}{harness}" for part in range(1, REMINDER_PARTS + 1)]
    runs = hook_commands(config, "reminder.py")
    assert runs
    assert runs == dict.fromkeys(runs, expected)
