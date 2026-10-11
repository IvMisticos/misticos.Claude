import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hooks"))

from prose import prose_length
from reply_history import EventLog, Prompt, Reply, transcript_history

ROOT = Path(__file__).resolve().parent.parent
REPLY_NAGS = ROOT / "hooks" / "reply_nags.py"
LONG = "word " * 70
SHORT = "done"


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
def test_counts_prose_outside_code_and_links(text, length):
    assert prose_length(text) == length


def test_log_starts_at_the_reviewed_prompt():
    log = EventLog().with_reply(SHORT).with_prompt().with_reply(SHORT)
    log = log.with_prompt().starting_at("1")
    assert [type(item) for item in log.history] == [Prompt, Reply, Prompt]


@pytest.fixture
def home(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    return home


def run_hook(home, payload, *arguments):
    result = subprocess.run(
        [sys.executable, str(REPLY_NAGS), *arguments],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env={"HOME": str(home), "PATH": "/usr/bin:/bin"},
        check=True,
    )
    return json.loads(result.stdout) if result.stdout else None


def claude_context(output):
    return output["hookSpecificOutput"]["additionalContext"] if output else None


class Transcript:
    def __init__(self, path):
        self.path = path
        self.count = 0

    def add(self, entry):
        self.count += 1
        with self.path.open("a") as lines:
            lines.write(json.dumps({"uuid": f"u{self.count}", **entry}) + "\n")

    def human(self, text="hi"):
        self.add(
            {"type": "user", "origin": {"kind": "human"}, "message": {"content": text}}
        )

    def wake(self):
        origin = {"kind": "task-notification"}
        self.add({"type": "user", "origin": origin, "message": {"content": "<wake/>"}})

    def reply(self, text, message_id=None):
        message_id = message_id or f"m{self.count}"
        content = [{"type": "text", "text": text}]
        message = {"id": message_id, "model": "claude-opus-5-5", "content": content}
        self.add({"type": "assistant", "message": message})

    def tool_call(self, message_id):
        content = [{"type": "tool_use", "id": "t", "name": "Bash", "input": {}}]
        message = {"id": message_id, "model": "claude-opus-5-5", "content": content}
        self.add({"type": "assistant", "message": message})

    def fire(self, home, event="PostToolBatch"):
        payload = {
            "hook_event_name": event,
            "session_id": "s1",
            "transcript_path": str(self.path),
        }
        return claude_context(run_hook(home, payload))


@pytest.fixture
def transcript(tmp_path):
    return Transcript(tmp_path / "transcript.jsonl")


def test_merges_entries_of_one_message(transcript):
    transcript.human()
    transcript.reply("first half", "m")
    transcript.tool_call("m")
    transcript.reply("second half", "m")
    history = transcript_history(str(transcript.path))
    assert history == [Prompt("u1"), Reply("m", len("first half second half"))]


def test_nags_once_about_a_long_reply(home, transcript):
    transcript.human()
    transcript.reply(LONG)
    nag = transcript.fire(home)
    assert "at least 349 characters" in nag
    assert transcript.fire(home) is None


def test_stays_quiet_about_short_replies(home, transcript):
    transcript.human()
    transcript.reply(SHORT)
    assert transcript.fire(home) is None


def test_catches_a_long_reply_before_the_next_prompt(home, transcript):
    transcript.human()
    transcript.reply(SHORT)
    transcript.fire(home)
    transcript.reply(LONG)
    transcript.human()
    assert "at least 349 characters" in transcript.fire(home, "UserPromptSubmit")


def test_nags_after_2_messages_then_after_6_more(home, transcript):
    transcript.human()
    nagged_at = []
    for count in range(1, 15):
        transcript.reply(SHORT)
        transcript.wake()
        if transcript.fire(home):
            nagged_at.append(count)
    assert nagged_at == [2, 8, 14]


def test_counts_messages_sent_before_the_user_wrote_again(home, transcript):
    transcript.human()
    transcript.reply(SHORT)
    transcript.wake()
    transcript.reply(SHORT)
    transcript.human()
    nag = transcript.fire(home, "UserPromptSubmit")
    assert "2 messages in a row" in nag
    assert transcript.fire(home) is None


def test_a_user_message_starts_a_new_count(home, transcript):
    transcript.human()
    transcript.reply(SHORT)
    transcript.fire(home)
    transcript.human()
    transcript.reply(SHORT)
    assert transcript.fire(home) is None


def test_keeps_counting_after_the_prompt_leaves_the_transcript_tail(home, transcript):
    transcript.human()
    transcript.reply(SHORT)
    transcript.fire(home)
    transcript.path.write_text("")
    transcript.reply(SHORT)
    transcript.wake()
    transcript.reply(SHORT)
    assert "3 messages in a row" in transcript.fire(home)


def test_counts_replies_that_left_the_transcript_tail(home, transcript):
    transcript.human()
    nagged_at = []
    for count in range(1, 9):
        transcript.reply(SHORT)
        if transcript.fire(home):
            nagged_at.append(count)
        transcript.path.write_text("")
    assert nagged_at == [2, 8]


def test_a_prompt_missing_from_the_tail_still_starts_a_new_count(home, transcript):
    transcript.human()
    transcript.reply(SHORT)
    transcript.fire(home, "UserPromptSubmit")
    transcript.path.write_text("")
    transcript.reply(SHORT)
    assert transcript.fire(home) is None


def test_skips_subagents(home, transcript):
    transcript.human()
    transcript.reply(LONG)
    payload = {
        "hook_event_name": "PostToolBatch",
        "session_id": "s1",
        "agent_id": "a1",
        "transcript_path": str(transcript.path),
    }
    assert run_hook(home, payload) is None


def codex(home, event, **fields):
    payload = {"hook_event_name": event, "session_id": "s1", **fields}
    return claude_context(run_hook(home, payload, "--harness", "codex"))


def test_codex_nags_about_the_last_turn_on_the_next_prompt(home):
    codex(home, "UserPromptSubmit", prompt="go")
    assert codex(home, "Stop", last_assistant_message=LONG) is None
    assert "at least 349 characters" in codex(home, "UserPromptSubmit", prompt="next")


def cursor(home, event, **fields):
    payload = {"hook_event_name": event, "conversation_id": "c1", **fields}
    output = run_hook(home, payload, "--harness", "cursor")
    return output["additional_context"] if output else None


def test_cursor_keeps_long_replies_from_turns_without_tools(home):
    cursor(home, "beforeSubmitPrompt", prompt="go")
    cursor(home, "afterAgentResponse", text=LONG)
    cursor(home, "beforeSubmitPrompt", prompt="next")
    cursor(home, "afterAgentResponse", text=SHORT)
    cursor(home, "beforeSubmitPrompt", prompt="again")
    assert "at least 349 characters" in cursor(home, "postToolUse")


def test_cursor_counts_the_answer_after_the_last_tool(home):
    cursor(home, "beforeSubmitPrompt", prompt="go")
    cursor(home, "afterAgentResponse", text="Checking.")
    assert cursor(home, "postToolUse") is None
    cursor(home, "afterAgentResponse", text="Done.")
    cursor(home, "beforeSubmitPrompt", prompt="next")
    assert "2 messages in a row" in cursor(home, "postToolUse")
    assert cursor(home, "postToolUse") is None


def test_cursor_keeps_only_nags_from_the_last_turn_without_tools(home):
    for _ in range(3):
        cursor(home, "beforeSubmitPrompt", prompt="go")
        cursor(home, "afterAgentResponse", text=SHORT)
        cursor(home, "afterAgentResponse", text=SHORT)
    cursor(home, "beforeSubmitPrompt", prompt="next")
    assert cursor(home, "postToolUse").count("messages in a row") == 1


def test_cursor_nags_about_repeated_updates_after_a_tool(home):
    cursor(home, "beforeSubmitPrompt", prompt="go")
    cursor(home, "afterAgentResponse", text=SHORT)
    cursor(home, "afterAgentResponse", text=SHORT)
    assert "2 messages in a row" in cursor(home, "postToolUse")
