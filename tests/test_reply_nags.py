from collections.abc import Callable
from pathlib import Path

import pytest
from conftest import (
    append_json_lines,
    home_environment,
    run_json_hook,
    text_at,
)
from json_values import JsonObject, JsonValue
from prose import prose_length
from reply_history import EventLog, Prompt, Reply, transcript_history

ROOT = Path(__file__).resolve().parent.parent
REPLY_NAGS = ROOT / "hooks" / "reply_nags.py"
LONG = "word " * 250
SHORT = "done"
WAKE_PROMPTS = [
    "<task-notification>\n<task-id>b343utgl5</task-id>",
    '\n<agent-message from="worker">done</agent-message>',
    "Another Claude session sent a message:\ndone",
]


@pytest.mark.parametrize(
    ("text", "length"),
    [
        ("plain words", 11),
        ("before\n```python\nprint('x' * 900)\n```\nafter", 12),
        ("open fence\n~~~\nnever closed", 10),
        ("short\n```\ncode\n````\nlong closer", 17),
        ("shown\n~~~\n```\n~~~\nafter", 11),
        ("run `make test` now", 7),
        ("see [the PR](https://github.com/a/b/pull/1) ok", 13),
        ("link https://example.com/very/long/path here", 9),
        ("auto <https://example.com> link", 9),
        ("spaced   \n\n  out", 10),
    ],
)
def test_counts_prose_outside_code_and_links(text: str, length: int) -> None:
    assert prose_length(text) == length


def test_log_starts_at_the_reviewed_prompt() -> None:
    log = EventLog().with_reply(SHORT).with_prompt().with_reply(SHORT)
    log = log.with_prompt().starting_at("1")
    assert [type(item) for item in log.history] == [Prompt, Reply, Prompt]


def run_hook(home: Path, payload: JsonObject, *arguments: str) -> JsonValue:
    return run_json_hook(REPLY_NAGS, payload, *arguments, env=home_environment(home))


def claude_context(output: JsonValue) -> str | None:
    return (
        text_at(output, "hookSpecificOutput", "additionalContext") if output else None
    )


def nag_text(nag: str | None) -> str:
    assert nag is not None
    return nag


class Transcript:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.count = 0

    def add(self, entry: JsonObject) -> None:
        self.count += 1
        append_json_lines(self.path, {"uuid": f"u{self.count}", **entry})

    def human(self, text: str = "hi") -> None:
        self.add(
            {"type": "user", "origin": {"kind": "human"}, "message": {"content": text}}
        )

    def wake(self, text: str = WAKE_PROMPTS[0]) -> None:
        origin: JsonObject = {"kind": "task-notification"}
        self.add({"type": "user", "origin": origin, "message": {"content": text}})

    def queued(self, kind: str, text: str) -> None:
        origin: JsonObject = {"kind": kind}
        attachment: JsonObject = {
            "type": "queued_command",
            "origin": origin,
            "prompt": text,
        }
        self.add({"type": "attachment", "attachment": attachment})

    def queued_wake(self, text: str = WAKE_PROMPTS[0]) -> None:
        self.queued("task-notification", text)

    def queued_human(self, text: str = "queued") -> None:
        self.queued("human", text)

    def reply(self, text: str, message_id: str | None = None) -> None:
        message_id = message_id or f"m{self.count}"
        content: list[JsonValue] = [{"type": "text", "text": text}]
        message: JsonObject = {
            "id": message_id,
            "model": "claude-opus-5-5",
            "content": content,
        }
        self.add({"type": "assistant", "message": message})

    def tool_call(self, message_id: str | None) -> None:
        content: list[JsonValue] = [
            {"type": "tool_use", "id": "t", "name": "Bash", "input": {}}
        ]
        message: JsonObject = {
            "id": message_id,
            "model": "claude-opus-5-5",
            "content": content,
        }
        self.add({"type": "assistant", "message": message})

    def fire(
        self, home: Path, event: str = "PostToolBatch", **fields: JsonValue
    ) -> str | None:
        payload: JsonObject = {
            "hook_event_name": event,
            "session_id": "s1",
            "transcript_path": str(self.path),
            **fields,
        }
        return claude_context(run_hook(home, payload))

    def submit(self, home: Path, prompt: str) -> str | None:
        prompt_id = f"prompt-{self.count}"
        return self.fire(home, "UserPromptSubmit", prompt=prompt, prompt_id=prompt_id)

    def submit_human(self, home: Path, text: str = "hi") -> str | None:
        nag = self.submit(home, text)
        self.human(text)
        return nag


@pytest.fixture
def transcript(tmp_path: Path) -> Transcript:
    return Transcript(tmp_path / "transcript.jsonl")


def test_merges_entries_of_one_message(transcript: Transcript) -> None:
    transcript.human()
    transcript.reply("first half", "m")
    transcript.tool_call("m")
    transcript.reply("second half", "m")
    history = transcript_history(str(transcript.path))
    assert history == [Prompt("u1"), Reply("m", len("first half second half"))]


def test_nags_once_about_a_long_reply(home: Path, transcript: Transcript) -> None:
    transcript.human()
    transcript.reply(LONG)
    nag = transcript.fire(home)
    assert "at least 1249 characters" in nag_text(nag)
    assert transcript.fire(home) is None


def test_stays_quiet_about_short_replies(home: Path, transcript: Transcript) -> None:
    transcript.human()
    transcript.reply(SHORT)
    assert transcript.fire(home) is None


def test_catches_a_long_reply_before_the_next_prompt(
    home: Path, transcript: Transcript
) -> None:
    transcript.human()
    transcript.reply(SHORT)
    transcript.fire(home)
    transcript.reply(LONG)
    assert "at least 1249 characters" in nag_text(transcript.submit_human(home))


def test_nags_after_2_messages_then_after_6_more(
    home: Path, transcript: Transcript
) -> None:
    transcript.human()
    nagged_at = []
    for count in range(1, 15):
        transcript.reply(SHORT)
        transcript.wake()
        if transcript.fire(home):
            nagged_at.append(count)
    assert nagged_at == [2, 8, 14]


@pytest.mark.parametrize("prompt", WAKE_PROMPTS)
@pytest.mark.parametrize("add_wake", [Transcript.wake, Transcript.queued_wake])
def test_wakes_that_submit_a_prompt_keep_the_cadence(
    home: Path,
    transcript: Transcript,
    prompt: str,
    add_wake: Callable[[Transcript, str], None],
) -> None:
    transcript.submit_human(home)
    nagged_at = []
    for count in range(1, 15):
        transcript.reply(SHORT)
        nags = [transcript.fire(home), transcript.submit(home, prompt)]
        add_wake(transcript, prompt)
        nags.append(transcript.fire(home))
        nagged_at += [count for nag in nags if nag]
    assert nagged_at == [2, 8, 14]


def test_wakes_with_an_unknown_start_keep_the_cadence(
    home: Path, transcript: Transcript
) -> None:
    transcript.submit_human(home)
    nagged_at = []
    for count in range(1, 15):
        transcript.reply(SHORT)
        nags = [transcript.fire(home), transcript.submit(home, "<unknown-wake>")]
        transcript.wake("<unknown-wake>")
        nags.append(transcript.fire(home))
        nagged_at += [count for nag in nags if nag]
    assert nagged_at == [2, 8, 14]


def test_a_wake_after_a_new_prompt_ignores_the_old_count(
    home: Path, transcript: Transcript
) -> None:
    transcript.submit_human(home)
    for _ in range(3):
        transcript.reply(SHORT)
        transcript.fire(home)
    transcript.submit_human(home)
    transcript.tool_call("tools")
    transcript.fire(home)
    assert transcript.submit(home, WAKE_PROMPTS[0]) is None


def test_a_human_prompt_after_wakes_restarts_the_cadence(
    home: Path, transcript: Transcript
) -> None:
    transcript.submit_human(home)
    for _ in range(5):
        transcript.reply(SHORT)
        transcript.fire(home)
        transcript.submit(home, WAKE_PROMPTS[0])
        transcript.wake()
    transcript.submit_human(home)
    transcript.reply(SHORT)
    assert transcript.fire(home) is None
    transcript.reply(SHORT)
    assert "2 messages in a row" in nag_text(transcript.fire(home))


def test_counts_messages_sent_before_the_user_wrote_again(
    home: Path, transcript: Transcript
) -> None:
    transcript.human()
    transcript.reply(SHORT)
    transcript.wake()
    transcript.reply(SHORT)
    nag = transcript.submit_human(home)
    assert "2 messages in a row" in nag_text(nag)
    assert transcript.fire(home) is None


def test_a_user_message_starts_a_new_count(home: Path, transcript: Transcript) -> None:
    transcript.human()
    transcript.reply(SHORT)
    transcript.fire(home)
    transcript.human()
    transcript.reply(SHORT)
    assert transcript.fire(home) is None


def test_keeps_counting_after_the_prompt_leaves_the_transcript_tail(
    home: Path, transcript: Transcript
) -> None:
    transcript.human()
    transcript.reply(SHORT)
    transcript.fire(home)
    transcript.path.write_text("")
    transcript.reply(SHORT)
    transcript.wake()
    transcript.reply(SHORT)
    assert "3 messages in a row" in nag_text(transcript.fire(home))


def test_counts_replies_that_left_the_transcript_tail(
    home: Path, transcript: Transcript
) -> None:
    transcript.human()
    nagged_at = []
    for count in range(1, 9):
        transcript.reply(SHORT)
        if transcript.fire(home):
            nagged_at.append(count)
        transcript.path.write_text("")
    assert nagged_at == [2, 8]


def test_a_prompt_missing_from_the_tail_still_starts_a_new_count(
    home: Path, transcript: Transcript
) -> None:
    transcript.human()
    transcript.reply(SHORT)
    transcript.submit(home, "hi")
    transcript.path.write_text("")
    transcript.reply(SHORT)
    assert transcript.fire(home) is None


def test_a_prompt_larger_than_the_tail_starts_a_new_count(
    home: Path, transcript: Transcript
) -> None:
    transcript.human()
    transcript.reply(SHORT)
    transcript.fire(home)
    transcript.submit_human(home, "x" * (2 << 20))
    transcript.reply(SHORT)
    assert transcript.fire(home) is None


@pytest.mark.parametrize("submitted", [False, True])
def test_a_message_typed_mid_turn_starts_a_new_count(
    home: Path, transcript: Transcript, submitted: bool
) -> None:
    transcript.human()
    transcript.reply(SHORT)
    transcript.fire(home)
    if submitted:
        transcript.submit(home, "queued")
    transcript.queued_human()
    transcript.reply(SHORT)
    assert transcript.fire(home) is None


def test_a_message_drained_with_a_wake_starts_a_new_count(
    home: Path, transcript: Transcript
) -> None:
    transcript.human()
    transcript.reply(SHORT)
    transcript.fire(home)
    transcript.submit(home, WAKE_PROMPTS[0])
    transcript.queued_human()
    transcript.queued_wake()
    transcript.reply(SHORT)
    assert transcript.fire(home) is None


def test_skips_subagents(home: Path, transcript: Transcript) -> None:
    transcript.human()
    transcript.reply(LONG)
    payload: JsonObject = {
        "hook_event_name": "PostToolBatch",
        "session_id": "s1",
        "agent_id": "a1",
        "transcript_path": str(transcript.path),
    }
    assert run_hook(home, payload) is None


def codex(home: Path, event: str, **fields: JsonValue) -> str | None:
    payload: JsonObject = {"hook_event_name": event, "session_id": "s1", **fields}
    return claude_context(run_hook(home, payload, "--harness", "codex"))


def test_codex_nags_about_the_last_turn_on_the_next_prompt(home: Path) -> None:
    codex(home, "UserPromptSubmit", prompt="go")
    assert codex(home, "Stop", last_assistant_message=LONG) is None
    assert "at least 1249 characters" in nag_text(
        codex(home, "UserPromptSubmit", prompt="next")
    )


def cursor(home: Path, event: str, **fields: JsonValue) -> str | None:
    payload: JsonObject = {"hook_event_name": event, "conversation_id": "c1", **fields}
    output = run_hook(home, payload, "--harness", "cursor")
    return text_at(output, "additional_context") if output else None


def test_cursor_keeps_long_replies_from_turns_without_tools(home: Path) -> None:
    cursor(home, "beforeSubmitPrompt", prompt="go")
    cursor(home, "afterAgentResponse", text=LONG)
    cursor(home, "beforeSubmitPrompt", prompt="next")
    cursor(home, "afterAgentResponse", text=SHORT)
    cursor(home, "beforeSubmitPrompt", prompt="again")
    assert "at least 1249 characters" in nag_text(cursor(home, "postToolUse"))


def test_cursor_counts_the_answer_after_the_last_tool(home: Path) -> None:
    cursor(home, "beforeSubmitPrompt", prompt="go")
    cursor(home, "afterAgentResponse", text="Checking.")
    assert cursor(home, "postToolUse") is None
    cursor(home, "afterAgentResponse", text="Done.")
    cursor(home, "beforeSubmitPrompt", prompt="next")
    assert "2 messages in a row" in nag_text(cursor(home, "postToolUse"))
    assert cursor(home, "postToolUse") is None


def test_cursor_keeps_only_nags_from_the_last_turn_without_tools(home: Path) -> None:
    for _ in range(3):
        cursor(home, "beforeSubmitPrompt", prompt="go")
        cursor(home, "afterAgentResponse", text=SHORT)
        cursor(home, "afterAgentResponse", text=SHORT)
    cursor(home, "beforeSubmitPrompt", prompt="next")
    assert nag_text(cursor(home, "postToolUse")).count("messages in a row") == 1


def test_cursor_nags_about_repeated_updates_after_a_tool(home: Path) -> None:
    cursor(home, "beforeSubmitPrompt", prompt="go")
    cursor(home, "afterAgentResponse", text=SHORT)
    cursor(home, "afterAgentResponse", text=SHORT)
    assert "2 messages in a row" in nag_text(cursor(home, "postToolUse"))
