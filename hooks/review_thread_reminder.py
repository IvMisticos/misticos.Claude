#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///

import os

from harnesses import harness_parser
from hook_io import read_payload, run_hook, write_block
from pull_requests import touched_pull_requests
from review_threads import thread_source, unresolved_threads_by_pull_request
from session_state import STATE_ROOT, locked_session_file, read_json, write_json
from transcript import dict_or_empty

STATE_DIR = os.path.join(STATE_ROOT, "review-threads")
SUBAGENT_STOP = "subagentstop"
ADVICE = "Resolve the ones you addressed; leave open only those waiting on the user."


def follows_own_block(payload):
    loop_count = payload.get("loop_count")
    return payload.get("stop_hook_active") is True or (
        isinstance(loop_count, int) and loop_count > 0
    )


def stopped_on_purpose(payload):
    return payload.get("status", "completed") != "completed"


def own_transcript(payload):
    event = str(payload.get("hook_event_name") or "").lower()
    if event == SUBAGENT_STOP:
        return payload.get("agent_transcript_path")
    return payload.get("transcript_path")


def parsed_seen(stored):
    return {
        thread_id: comment_id
        for thread_id, comment_id in dict_or_empty(stored).items()
        if isinstance(comment_id, int)
    }


def unseen_activity(threads, seen):
    return [
        thread for thread in threads if seen.get(thread.id) != thread.last_comment_id
    ]


def threads_with_new_comments(threads_by_pull_request, seen):
    changed = {
        pull_request: unseen_activity(threads, seen)
        for pull_request, threads in threads_by_pull_request.items()
    }
    return {
        pull_request: threads for pull_request, threads in changed.items() if threads
    }


def last_comments(threads_by_pull_request):
    return {
        thread.id: thread.last_comment_id
        for threads in threads_by_pull_request.values()
        for thread in threads
    }


def claim_new_activity(session_id, threads_by_pull_request):
    with locked_session_file(STATE_DIR, session_id) as state_file:
        seen = parsed_seen(read_json(state_file))
        changed = threads_with_new_comments(threads_by_pull_request, seen)
        write_json(state_file, seen | last_comments(threads_by_pull_request))
    return changed


def pull_request_line(pull_request, threads):
    if len(threads) == 1:
        return (
            f"PR {pull_request} has 1 review thread with new comments "
            "that is still unresolved."
        )
    return (
        f"PR {pull_request} has {len(threads)} review threads with new comments "
        "that are still unresolved."
    )


def reminder(changed):
    lines = [pull_request_line(*item) for item in changed.items()]
    return " ".join([*lines, ADVICE])


def main():
    options = harness_parser().parse_args()
    payload = read_payload()
    if follows_own_block(payload) or stopped_on_purpose(payload):
        return
    session_id = payload.get("session_id") or payload.get("conversation_id")
    transcript_path = own_transcript(payload)
    if not (isinstance(session_id, str) and isinstance(transcript_path, str)):
        return
    pull_requests = touched_pull_requests(transcript_path)
    threads = unresolved_threads_by_pull_request(pull_requests, thread_source())
    changed = claim_new_activity(session_id, threads) if threads else {}
    if changed:
        write_block(reminder(changed), options.harness.output_shape)


if __name__ == "__main__":
    run_hook(main)
