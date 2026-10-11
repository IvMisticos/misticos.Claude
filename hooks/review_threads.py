import json
import os
import shutil
import subprocess
import time
from collections.abc import Callable
from enum import Enum, auto
from typing import NamedTuple

GH_TIMEOUT_SECONDS = 10
NOT_FOUND_ERRORS = ("(HTTP 404)", "Could not resolve to a")
FINISHED_OUTPUT_WAIT_SECONDS = 0.1
THREADS_QUERY = """
query($owner: String!, $repo: String!, $number: Int!) {
  repository(owner: $owner, name: $repo) {
    pullRequest(number: $number) {
      state
      reviewThreads(last: 100) {
        nodes { id isResolved comments(last: 1) { nodes { databaseId } } }
      }
    }
  }
}
"""


class ReviewThread(NamedTuple):
    id: str
    last_comment_id: int


class ReviewState(NamedTuple):
    is_open: bool
    unresolved_threads: tuple = ()


NOT_OPEN = ReviewState(is_open=False)


class CallFailure(Enum):
    NOT_FOUND = auto()
    RETRYABLE = auto()


FAILURES_BY_PRIORITY = (CallFailure.RETRYABLE, CallFailure.NOT_FOUND)


class ThreadSource(NamedTuple):
    requests: Callable
    parse: Callable


def graphql_requests(pull_request):
    return [
        [
            "gh",
            "api",
            "graphql",
            "-f",
            f"query={THREADS_QUERY}",
            "-f",
            f"owner={pull_request.owner}",
            "-f",
            f"repo={pull_request.repo}",
            "-F",
            f"number={pull_request.number}",
        ]
    ]


def graphql_review_state(output):
    try:
        pull_request = json.loads(output)["data"]["repository"]["pullRequest"]
        if pull_request["state"] != "OPEN":
            return NOT_OPEN
        return ReviewState(
            is_open=True,
            unresolved_threads=tuple(
                ReviewThread(node["id"], node["comments"]["nodes"][-1]["databaseId"])
                for node in pull_request["reviewThreads"]["nodes"]
                if not node["isResolved"]
            ),
        )
    except (json.JSONDecodeError, KeyError, TypeError, IndexError):
        return None


def remote_requests(pull_request):
    path = f"repos/{pull_request.owner}/{pull_request.repo}/pulls/{pull_request.number}"
    return [
        ["gh", "api", path, "--jq", ".state"],
        ["gh", "api", f"{path}/ccr/review_threads"],
    ]


def remote_review_state(state_output, threads_output):
    state = state_output.strip()
    if state == "closed":
        return NOT_OPEN
    if state != "open":
        return None
    try:
        return ReviewState(
            is_open=True,
            unresolved_threads=tuple(
                ReviewThread(str(thread["comment_ids"][0]), thread["comment_ids"][-1])
                for thread in json.loads(threads_output)
                if not thread["resolved"]
            ),
        )
    except (json.JSONDecodeError, KeyError, TypeError, IndexError):
        return None


GRAPHQL = ThreadSource(graphql_requests, graphql_review_state)
REMOTE = ThreadSource(remote_requests, remote_review_state)


def thread_source():
    return REMOTE if os.environ.get("CLAUDE_CODE_REMOTE") == "true" else GRAPHQL


def started(command):
    return subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def time_left(deadline):
    return max(FINISHED_OUTPUT_WAIT_SECONDS, deadline - time.monotonic())


def failure_from(error):
    if any(marker in error for marker in NOT_FOUND_ERRORS):
        return CallFailure.NOT_FOUND
    return CallFailure.RETRYABLE


def output_by(deadline, process):
    try:
        output, error = process.communicate(timeout=time_left(deadline))
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate()
        return CallFailure.RETRYABLE
    return output if process.returncode == 0 else failure_from(error)


def first_failure(outputs):
    return next((f for f in FAILURES_BY_PRIORITY if f in outputs), None)


def review_state_from(outputs, source):
    match first_failure(outputs):
        case CallFailure.RETRYABLE:
            return None
        case CallFailure.NOT_FOUND:
            return NOT_OPEN
        case None:
            return source.parse(*outputs)


def gh_installed():
    return shutil.which("gh") is not None


def review_states(pull_requests, source):
    running = {
        pull_request: [started(command) for command in source.requests(pull_request)]
        for pull_request in pull_requests
    }
    deadline = time.monotonic() + GH_TIMEOUT_SECONDS
    states = {}
    for pull_request, processes in running.items():
        outputs = [output_by(deadline, process) for process in processes]
        state = review_state_from(outputs, source)
        if state is not None:
            states[pull_request] = state
    return states
