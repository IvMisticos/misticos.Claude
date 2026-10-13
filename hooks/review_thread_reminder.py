#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# [tool.ty.environment]
# root = ["."]
# ///

import copy
from typing import NamedTuple

from harnesses import harness_parser
from hook_io import (
    agent_session_key,
    event_name_of,
    read_payload,
    run_hook,
    write_block,
)
from plugin_paths import DATA_ROOT
from pull_requests import last_activity_by_pull_request
from review_threads import gh_installed, review_states, thread_source
from session_state import locked_session_file, read_record, write_record
from transcript import positioned_entries, transcript_part_from

STATE_DIR = DATA_ROOT / "review-threads"
SUBAGENT_STOP = "subagentstop"


class Memory(NamedTuple):
    seen: dict[str, int]
    skipped: tuple[str, ...]
    checked: dict[str, int]
    scanned: int = 0


EMPTY_MEMORY = Memory(seen={}, skipped=(), checked={}, scanned=0)


def follows_own_block(payload):
    loop_count = payload.get("loop_count")
    return payload.get("stop_hook_active") is True or (
        isinstance(loop_count, int) and loop_count > 0
    )


def ended_without_completing(payload):
    return payload.get("status", "completed") != "completed"


def own_transcript(payload):
    if event_name_of(payload).lower() == SUBAGENT_STOP:
        return payload.get("agent_transcript_path")
    return payload.get("transcript_path")


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


def updated_memory(memory, states, activity, scanned):
    skipped = {
        str(pull_request) for pull_request, state in states.items() if not state.is_open
    }
    checked = {str(pull_request): activity[pull_request] for pull_request in states}
    return Memory(
        seen=memory.seen | last_comments(open_threads(states)),
        skipped=tuple(sorted({*memory.skipped, *skipped})),
        checked=memory.checked | checked,
        scanned=scanned,
    )


def next_scan_start(part, activity, states):
    all_answered = all(pull_request in states for pull_request in activity)
    return part.end if all_answered else part.start


def matching_offsets(memory, part):
    if part.start < memory.scanned:
        return copy.replace(memory, checked={}, scanned=part.start)
    return memory


def scanned_memory(memory, part, activity, states):
    scanned = next_scan_start(part, activity, states)
    return updated_memory(matching_offsets(memory, part), states, activity, scanned)


def remember_scan(key, part, activity, states):
    with locked_session_file(STATE_DIR, key) as state_file:
        memory_before = read_record(state_file, EMPTY_MEMORY)
        write_record(state_file, scanned_memory(memory_before, part, activity, states))
    return memory_before


def reminder(changed):
    return " ".join(
        f"PR {pull_request} has unresolved review threads with new comments."
        for pull_request in changed
    )


def has_unchecked_activity(memory, pull_request, position):
    name = str(pull_request)
    return name not in memory.skipped and position > memory.checked.get(name, -1)


def new_activity(part, memory):
    activity = last_activity_by_pull_request(positioned_entries(part))
    return {
        pull_request: position
        for pull_request, position in activity.items()
        if has_unchecked_activity(memory, pull_request, position)
    }


def review_reminder(payload):
    if follows_own_block(payload) or ended_without_completing(payload):
        return None
    key = agent_session_key(payload)
    transcript_path = own_transcript(payload)
    if not (key and isinstance(transcript_path, str) and gh_installed()):
        return None
    memory = remembered(key)
    part = transcript_part_from(transcript_path, memory.scanned)
    activity = new_activity(part, matching_offsets(memory, part))
    states = review_states(list(activity), thread_source())
    memory_before_scan = remember_scan(key, part, activity, states)
    changed = threads_with_new_comments(open_threads(states), memory_before_scan.seen)
    return reminder(changed) if changed else None


def main():
    options = harness_parser().parse_args()
    reason = review_reminder(read_payload())
    if reason:
        write_block(reason, options.harness.output_shape)


if __name__ == "__main__":
    run_hook(main)
