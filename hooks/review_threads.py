import json
import os
import shutil
import subprocess
import time
from collections.abc import Callable
from typing import NamedTuple

GH_TIMEOUT_SECONDS = 10
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


CLOSED = ReviewState(is_open=False)


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
            return CLOSED
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
    if state_output.strip() != "open":
        return CLOSED
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
        stderr=subprocess.DEVNULL,
        text=True,
    )


def time_left(deadline):
    return max(FINISHED_OUTPUT_WAIT_SECONDS, deadline - time.monotonic())


def output_by(deadline, process):
    try:
        output, _ = process.communicate(timeout=time_left(deadline))
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate()
        return None
    return output if process.returncode == 0 else None


def review_states(pull_requests, source):
    if not shutil.which("gh"):
        return {}
    running = {
        pull_request: [started(command) for command in source.requests(pull_request)]
        for pull_request in pull_requests
    }
    deadline = time.monotonic() + GH_TIMEOUT_SECONDS
    states = {}
    for pull_request, processes in running.items():
        outputs = [output_by(deadline, process) for process in processes]
        state = None if None in outputs else source.parse(*outputs)
        if state is not None:
            states[pull_request] = state
    return states
