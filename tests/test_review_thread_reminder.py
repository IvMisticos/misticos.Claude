import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hooks"))

from pull_requests import PullRequest, last_activity_by_pull_request
from review_threads import output_by, started

ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / "hooks" / "review_thread_reminder.py"
PULL_REQUEST = PullRequest("acme", "widgets", 7)
ADVICE = "Resolve the ones you addressed; leave open the ones waiting on someone else."
FAKE_GH = """#!/bin/bash
printf '%s\\n' "$*" >> {responses}/calls.log
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


def add_activity(transcript):
    event = f'<event>{{"pr":"{PULL_REQUEST}"}}</event>'
    with transcript.open("a") as lines:
        lines.write(json.dumps({"type": "user", "message": {"content": event}}) + "\n")


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


def blocked():
    reason = (
        f"PR {PULL_REQUEST} has review threads with new comments "
        f"that are still unresolved. {ADVICE}"
    )
    return {"decision": "block", "reason": reason}


def test_new_unresolved_thread_blocks_once(home, gh_path, responses, transcript):
    answer_graphql(responses, Thread("T1", [1]), Thread("T2", [2, 3]))
    assert run_hook(home, gh_path, stop(transcript)) == blocked()
    assert run_hook(home, gh_path, stop(transcript)) is None


def test_stop_without_new_activity_calls_no_gh(home, gh_path, responses, transcript):
    answer_graphql(responses, Thread("T1", [1]))
    run_hook(home, gh_path, stop(transcript))
    answer_graphql(responses, Thread("T1", [1, 2]))
    calls = responses / "calls.log"
    calls.unlink()
    assert run_hook(home, gh_path, stop(transcript)) is None
    assert not calls.exists()


def test_new_comment_on_a_seen_thread_blocks_again(
    home, gh_path, responses, transcript
):
    answer_graphql(responses, Thread("T1", [1]), Thread("T2", [2]))
    run_hook(home, gh_path, stop(transcript))
    answer_graphql(responses, Thread("T1", [1]), Thread("T2", [2, 4]))
    add_activity(transcript)
    assert run_hook(home, gh_path, stop(transcript)) == blocked()


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
    assert run_hook(home, gh_path, stop(transcript)) == blocked()


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


def test_subagent_leaves_the_parent_reminder_unclaimed(
    home, gh_path, responses, transcript
):
    answer_graphql(responses, Thread("T1", [1]))
    subagent = stop(
        transcript,
        hook_event_name="SubagentStop",
        agent_id="a1",
        agent_transcript_path=str(transcript),
    )
    assert run_hook(home, gh_path, subagent) == blocked()
    assert run_hook(home, gh_path, stop(transcript)) == blocked()


@pytest.mark.parametrize("gh_answers", [True, False])
def test_pull_request_seen_not_open_is_not_queried_again(
    home, gh_path, responses, transcript, gh_answers
):
    if gh_answers:
        answer_graphql(responses, state="MERGED")
    run_hook(home, gh_path, stop(transcript))
    calls = responses / "calls.log"
    calls.unlink()
    add_activity(transcript)
    assert run_hook(home, gh_path, stop(transcript)) is None
    assert not calls.exists()


def test_call_that_finished_counts_after_the_deadline():
    process = started([sys.executable, "-c", "print('done')"])
    process.wait()
    assert output_by(time.monotonic() - 1, process) == "done\n"


def test_remote_session_reads_review_threads_route(
    home, gh_path, responses, transcript
):
    answer_remote(responses, Thread("T1", [1, 5]), Thread("T2", [2], resolved=True))
    assert run_hook(home, gh_path, stop(transcript), remote=True) == blocked()
    answer_remote(responses, Thread("T1", [1, 5, 6]), state="closed")
    add_activity(transcript)
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
    assert output == {"followup_message": blocked()["reason"]}


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


def assistant_call(block):
    return {"type": "assistant", "message": {"content": [block]}}


def tool_result(call_id, text):
    result = {"type": "tool_result", "tool_use_id": call_id, "content": text}
    return {"type": "user", "message": {"content": [result]}}


def bash_call(command, call_id="b0"):
    command_input = {"command": command}
    return {"type": "tool_use", "id": call_id, "name": "Bash", "input": command_input}


def test_finds_pull_requests_the_session_worked_on(tmp_path):
    create = {
        "type": "tool_use",
        "id": "c1",
        "name": "mcp__github__create_pull_request",
        "input": {"owner": "acme", "repo": "widgets", "title": "Add widgets"},
    }
    created = {"id": "1", "url": "https://github.com/acme/widgets/pull/9"}
    event = 'activity <event>{"pr":"acme/gadgets#3"}</event>'
    codex_call = {
        "type": "function_call",
        "name": "mcp__github__pull_request_read",
        "call_id": "x1",
        "arguments": json.dumps({"owner": "acme", "repo": "tools", "pullNumber": 4}),
    }
    codex_create = {
        "type": "function_call",
        "call_id": "call_1",
        "name": "shell",
        "arguments": json.dumps({"command": ["bash", "-lc", "gh pr create --fill"]}),
    }
    codex_created = {
        "type": "function_call_output",
        "call_id": "call_1",
        "output": "https://github.com/acme/apps/pull/8\n",
    }
    transcript = tmp_path / "transcript.jsonl"
    write_lines(
        transcript,
        tool_use(PULL_REQUEST),
        assistant_call(create),
        tool_result("c1", json.dumps(created)),
        {"type": "user", "message": {"content": event}},
        {"type": "response_item", "payload": codex_call},
        assistant_call(bash_call("gh pr view https://github.com/acme/cli/pull/5")),
        assistant_call(bash_call("gh api repos/acme/api/pulls/6/comments")),
        assistant_call(bash_call("gh pr create --fill", call_id="b1")),
        tool_result("b1", "https://github.com/acme/web/pull/10\n"),
        {"type": "response_item", "payload": codex_create},
        {"type": "response_item", "payload": codex_created},
        tool_use(PULL_REQUEST),
    )
    assert list(last_activity_by_pull_request(transcript)) == [
        PULL_REQUEST,
        PullRequest("acme", "widgets", 9),
        PullRequest("acme", "gadgets", 3),
        PullRequest("acme", "tools", 4),
        PullRequest("acme", "cli", 5),
        PullRequest("acme", "api", 6),
        PullRequest("acme", "web", 10),
        PullRequest("acme", "apps", 8),
    ]


def test_ignores_pull_requests_the_session_only_saw(tmp_path):
    link = "https://github.com/acme/widgets/pull/2"
    listing = {
        "type": "tool_use",
        "id": "l1",
        "name": "mcp__github__list_pull_requests",
        "input": {"owner": "acme", "repo": "widgets"},
    }
    listed = {
        "html_url": "https://github.com/acme/widgets/pull/1",
        "url": "https://api.github.com/repos/acme/widgets/pulls/1",
    }
    fetch = {"type": "tool_use", "name": "WebFetch", "input": {"url": link}}
    write = {
        "type": "tool_use",
        "name": "Write",
        "input": {"content": f'see {link} and {{"pr":"acme/widgets#3"}}'},
    }
    transcript = tmp_path / "transcript.jsonl"
    write_lines(
        transcript,
        assistant_call(listing),
        tool_result("l1", json.dumps([listed])),
        assistant_call(fetch),
        assistant_call(write),
        assistant_call(bash_call(f"git commit -m 'Port {link}'")),
        {"type": "user", "message": {"content": f"Compare with {link}"}},
        assistant_call({"type": "text", "text": link}),
    )
    assert last_activity_by_pull_request(transcript) == {}


def test_codex_create_result_matches_by_call_id(tmp_path):
    create = {
        "type": "function_call",
        "id": "fc_1",
        "call_id": "call_1",
        "name": "mcp__github__create_pull_request",
        "arguments": json.dumps({"owner": "acme", "repo": "apps"}),
    }
    created = {
        "type": "function_call_output",
        "call_id": "call_1",
        "output": json.dumps({"url": "https://github.com/acme/apps/pull/8"}),
    }
    transcript = tmp_path / "transcript.jsonl"
    write_lines(
        transcript,
        {"type": "response_item", "payload": create},
        {"type": "response_item", "payload": created},
    )
    assert list(last_activity_by_pull_request(transcript)) == [
        PullRequest("acme", "apps", 8)
    ]


def test_create_call_without_id_reads_no_other_entries(tmp_path):
    create = {
        "type": "tool_use",
        "name": "mcp__github__create_pull_request",
        "input": {"owner": "acme", "repo": "widgets"},
    }
    prose = "Compare with https://github.com/acme/widgets/pull/2"
    transcript = tmp_path / "transcript.jsonl"
    write_lines(
        transcript,
        assistant_call(create),
        {"type": "user", "message": {"content": prose}},
    )
    assert last_activity_by_pull_request(transcript) == {}
