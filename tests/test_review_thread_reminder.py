import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hooks"))

from pull_requests import PullRequest, touched_pull_requests

ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / "hooks" / "review_thread_reminder.py"
PULL_REQUEST = PullRequest("acme", "widgets", 7)
ADVICE = "Resolve the ones you addressed; leave open the ones waiting on someone else."
FAKE_GH = """#!/bin/bash
case "$*" in
  *graphql*) response={responses}/graphql.json ;;
  *ccr/review_threads*) response={responses}/threads.json ;;
  *) response={responses}/state.txt ;;
esac
[ -f "$response" ] || exit 1
printf '%s\\n' "$(<"$response")"
"""


class Thread:
    def __init__(self, thread_id, comment_ids, resolved=False):
        self.id = thread_id
        self.comment_ids = comment_ids
        self.resolved = resolved

    def as_graphql(self):
        last_comment = {"databaseId": self.comment_ids[-1]}
        return {
            "id": self.id,
            "isResolved": self.resolved,
            "comments": {"nodes": [last_comment]},
        }

    def as_remote(self):
        return {
            "resolved": self.resolved,
            "outdated": False,
            "comment_ids": self.comment_ids,
        }


@pytest.fixture
def home(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    return home


@pytest.fixture
def responses(tmp_path):
    responses = tmp_path / "responses"
    responses.mkdir()
    return responses


@pytest.fixture
def gh_path(fake_bin, responses):
    return str(fake_bin("gh", FAKE_GH.format(responses=responses)))


@pytest.fixture
def transcript(tmp_path):
    transcript = tmp_path / "transcript.jsonl"
    write_lines(transcript, tool_use(PULL_REQUEST))
    return transcript


def write_lines(path, *entries):
    path.write_text("".join(json.dumps(entry) + "\n" for entry in entries))


def tool_use(pull_request):
    arguments = {
        "owner": pull_request.owner,
        "repo": pull_request.repo,
        "pullNumber": pull_request.number,
    }
    block = {"type": "tool_use", "name": "mcp__github__pull_request_read"}
    return {
        "type": "assistant",
        "message": {"content": [{**block, "input": arguments}]},
    }


def answer_graphql(responses, *threads, state="OPEN"):
    nodes = [thread.as_graphql() for thread in threads]
    pull_request = {"state": state, "reviewThreads": {"nodes": nodes}}
    response = {"data": {"repository": {"pullRequest": pull_request}}}
    (responses / "graphql.json").write_text(json.dumps(response))


def answer_remote(responses, *threads, state="open"):
    (responses / "state.txt").write_text(state)
    remote_threads = [thread.as_remote() for thread in threads]
    (responses / "threads.json").write_text(json.dumps(remote_threads))


def stop(transcript, **fields):
    return {
        "hook_event_name": "Stop",
        "session_id": "s1",
        "stop_hook_active": False,
        "transcript_path": str(transcript),
        **fields,
    }


def run_hook(home, path, payload, *arguments, remote=False):
    environment = {"HOME": str(home), "PATH": path}
    if remote:
        environment["CLAUDE_CODE_REMOTE"] = "true"
    result = subprocess.run(
        [sys.executable, str(HOOK), *arguments],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=environment,
        check=True,
    )
    return json.loads(result.stdout) if result.stdout else None


def blocked(count):
    threads = "1 review thread" if count == 1 else f"{count} review threads"
    verb = "is" if count == 1 else "are"
    reason = (
        f"PR {PULL_REQUEST} has {threads} with new comments "
        f"that {verb} still unresolved. {ADVICE}"
    )
    return {"decision": "block", "reason": reason}


def test_new_unresolved_thread_blocks_once(home, gh_path, responses, transcript):
    answer_graphql(responses, Thread("T1", [1]), Thread("T2", [2, 3]))
    assert run_hook(home, gh_path, stop(transcript)) == blocked(2)
    assert run_hook(home, gh_path, stop(transcript)) is None


def test_new_comment_on_a_seen_thread_blocks_again(
    home, gh_path, responses, transcript
):
    answer_graphql(responses, Thread("T1", [1]), Thread("T2", [2]))
    run_hook(home, gh_path, stop(transcript))
    answer_graphql(responses, Thread("T1", [1]), Thread("T2", [2, 4]))
    assert run_hook(home, gh_path, stop(transcript)) == blocked(1)


def test_resolved_thread_stays_silent(home, gh_path, responses, transcript):
    answer_graphql(responses, Thread("T1", [1], resolved=True))
    assert run_hook(home, gh_path, stop(transcript)) is None


@pytest.mark.parametrize("state", ["MERGED", "CLOSED"])
def test_finished_pull_request_stays_silent(
    home, gh_path, responses, transcript, state
):
    answer_graphql(responses, Thread("T1", [1]), state=state)
    assert run_hook(home, gh_path, stop(transcript)) is None


def test_gh_failure_stays_silent(home, gh_path, transcript):
    assert run_hook(home, gh_path, stop(transcript)) is None


def test_missing_gh_stays_silent(home, tmp_path, transcript):
    empty_bin = tmp_path / "empty"
    empty_bin.mkdir()
    assert run_hook(home, str(empty_bin), stop(transcript)) is None


def test_continuing_after_a_block_stays_silent_and_keeps_the_thread_new(
    home, gh_path, responses, transcript
):
    answer_graphql(responses, Thread("T1", [1]))
    active = stop(transcript, stop_hook_active=True)
    assert run_hook(home, gh_path, active) is None
    assert run_hook(home, gh_path, stop(transcript)) == blocked(1)


def test_subagent_checks_its_own_transcript(home, gh_path, responses, tmp_path):
    answer_graphql(responses, Thread("T1", [1]))
    parent = tmp_path / "parent.jsonl"
    write_lines(parent, tool_use(PULL_REQUEST))
    own = tmp_path / "agent.jsonl"
    write_lines(own, {"type": "assistant", "message": {"content": []}})
    payload = stop(
        parent, hook_event_name="SubagentStop", agent_transcript_path=str(own)
    )
    assert run_hook(home, gh_path, payload) is None


def test_remote_session_reads_review_threads_route(
    home, gh_path, responses, transcript
):
    answer_remote(responses, Thread("T1", [1, 5]), Thread("T2", [2], resolved=True))
    assert run_hook(home, gh_path, stop(transcript), remote=True) == blocked(1)
    answer_remote(responses, Thread("T1", [1, 5, 6]), state="closed")
    assert run_hook(home, gh_path, stop(transcript), remote=True) is None


def test_cursor_gets_a_follow_up_message(home, gh_path, responses, transcript):
    answer_graphql(responses, Thread("T1", [1]))
    payload = {
        "hook_event_name": "stop",
        "conversation_id": "c1",
        "status": "completed",
        "loop_count": 0,
        "transcript_path": str(transcript),
    }
    output = run_hook(home, gh_path, payload, "--harness", "cursor")
    assert output == {"followup_message": blocked(1)["reason"]}


@pytest.mark.parametrize(
    "fields", [{"loop_count": 1}, {"loop_count": 0, "status": "aborted"}]
)
def test_cursor_stays_silent_after_a_follow_up_or_abort(
    home, gh_path, responses, transcript, fields
):
    answer_graphql(responses, Thread("T1", [1]))
    payload = {
        "hook_event_name": "stop",
        "conversation_id": "c1",
        "transcript_path": str(transcript),
        **fields,
    }
    assert run_hook(home, gh_path, payload, "--harness", "cursor") is None


def test_finds_pull_requests_the_session_touched(tmp_path):
    created = {"id": "1", "url": "https://github.com/acme/widgets/pull/9"}
    created_result = {"type": "tool_result", "content": json.dumps(created)}
    event = 'activity <event>{"pr":"acme/gadgets#3"}</event>'
    codex_call = {
        "type": "function_call",
        "arguments": json.dumps({"owner": "acme", "repo": "tools", "pullNumber": 4}),
    }
    file_read = {"type": "tool_use", "input": {"owner": "acme", "repo": "widgets"}}
    transcript = tmp_path / "transcript.jsonl"
    write_lines(
        transcript,
        tool_use(PULL_REQUEST),
        {"type": "user", "message": {"content": [created_result]}},
        {"type": "user", "message": {"content": event}},
        {"type": "response_item", "payload": codex_call},
        {"type": "assistant", "message": {"content": [file_read]}},
        tool_use(PULL_REQUEST),
    )
    assert touched_pull_requests(transcript) == [
        PULL_REQUEST,
        PullRequest("acme", "widgets", 9),
        PullRequest("acme", "gadgets", 3),
        PullRequest("acme", "tools", 4),
    ]
