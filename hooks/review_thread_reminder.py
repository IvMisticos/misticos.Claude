#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///

import os
from typing import NamedTuple

from harnesses import harness_parser
from hook_io import read_payload, run_hook, write_block
from pull_requests import last_activity_by_pull_request
from review_threads import review_states, thread_source
from session_state import STATE_ROOT, locked_session_file, read_record, write_record

STATE_DIR = os.path.join(STATE_ROOT, "review-threads")
SUBAGENT_STOP = "subagentstop"


class Memory(NamedTuple):
    seen: dict
    skipped: tuple
    checked: dict


EMPTY_MEMORY = Memory(seen={}, skipped=(), checked={})


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


def memory_key(payload):
    session_id = payload.get("session_id") or payload.get("conversation_id")
    agent_id = payload.get("agent_id")
    if not isinstance(session_id, str):
        return None
    if isinstance(agent_id, str) and agent_id:
        return f"{session_id}-{agent_id}"
    return session_id


def remembered(key):
    with locked_session_file(STATE_DIR, key) as state_file:
        return read_record(state_file, EMPTY_MEMORY)


def open_threads(states):
    return {
        pull_request: state.unresolved_threads
        for pull_request, state in states.items()
        if state.is_open
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


def updated_memory(memory, states, activity):
    skipped = {
        str(pull_request) for pull_request, state in states.items() if not state.is_open
    }
    checked = {str(pull_request): activity[pull_request] for pull_request in states}
    return Memory(
        seen=memory.seen | last_comments(open_threads(states)),
        skipped=tuple(sorted({*memory.skipped, *skipped})),
        checked=memory.checked | checked,
    )


def claim_unseen_threads(key, states, activity):
    with locked_session_file(STATE_DIR, key) as state_file:
        memory = read_record(state_file, EMPTY_MEMORY)
        changed = threads_with_new_comments(open_threads(states), memory.seen)
        write_record(state_file, updated_memory(memory, states, activity))
    return changed


def reminder(changed):
    return " ".join(
        f"PR {pull_request} has unresolved review threads with new comments."
        for pull_request in changed
    )


def has_unchecked_activity(memory, pull_request, line_number):
    name = str(pull_request)
    return name not in memory.skipped and line_number > memory.checked.get(name, -1)


def new_activity(transcript_path, key):
    activity = last_activity_by_pull_request(transcript_path)
    if not activity:
        return {}
    memory = remembered(key)
    return {
        pull_request: line_number
        for pull_request, line_number in activity.items()
        if has_unchecked_activity(memory, pull_request, line_number)
    }


def main():
    options = harness_parser().parse_args()
    payload = read_payload()
    if follows_own_block(payload) or stopped_on_purpose(payload):
        return
    key = memory_key(payload)
    transcript_path = own_transcript(payload)
    if not (key and isinstance(transcript_path, str)):
        return
    activity = new_activity(transcript_path, key)
    states = review_states(list(activity), thread_source())
    changed = claim_unseen_threads(key, states, activity) if states else {}
    if changed:
        write_block(reminder(changed), options.harness.output_shape)


if __name__ == "__main__":
    run_hook(main)
