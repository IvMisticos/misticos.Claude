#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///

import json
import os
import re

from cleanup_policy import disk_cleanup
from disks import BYTES_PER_MIB, disks
from harnesses import harness_parser
from hook_io import read_payload, run_hook, scratchpad_of, write_context

LOW_SPACE_BYTES = 1 << 30
LOW_SPACE_SHARE = 0.1
OUT_OF_SPACE_ERROR = re.compile(
    r"[:\]]\s*(there is )?(no space left on device|disk quota exceeded"
    r"|not enough space on the disk|database or disk is full)",
    re.IGNORECASE,
)
READ_ONLY_TOOLS = {"Read", "Grep", "Glob", "LS", "WebFetch", "WebSearch"}
TOOL_RESULT_FIELDS = ("tool_response", "tool_output", "error_message")
TEMP_DIR_VARIABLES = ("TMPDIR", "TEMP", "TMP")
RUNNING_LOW = "Only {free} MiB of disk is free at {path}."
FREE_SPACE_NOW = "Free space now."
RAN_OUT = (
    "A tool result reports running out of disk space. If a write of yours "
    "failed, free space now. If you only read text that quotes such an "
    "error, ignore this."
)
HOW_TO_CLEAN_UP = (
    "Delete build output, package caches and clones you no longer need. Keep "
    "the uv cache: the hooks run from it. Delete only what you created or can "
    "regenerate."
)


def tool_calls(payload):
    calls = [payload, *(payload.get("tool_calls") or [])]
    return (call for call in calls if isinstance(call, dict))


def writing_tool_results(payload):
    return (
        json.dumps(call.get(field))
        for call in tool_calls(payload)
        if call.get("tool_name") not in READ_ONLY_TOOLS
        for field in TOOL_RESULT_FIELDS
    )


def ran_out_of_space(payload):
    results = writing_tool_results(payload)
    return any(OUT_OF_SPACE_ERROR.search(result) for result in results)


def watched_paths(payload):
    cwd = payload.get("cwd") or os.getcwd()
    temp_dirs = filter(None, map(os.environ.get, TEMP_DIR_VARIABLES))
    scratchpad = filter(None, [scratchpad_of(payload)])
    return (cwd, os.path.expanduser("~"), *temp_dirs, "/tmp", *scratchpad)


def is_low(disk):
    return disk.free < min(LOW_SPACE_BYTES, disk.total * LOW_SPACE_SHARE)


def disk_warning(payload):
    low_space = [
        RUNNING_LOW.format(free=disk.free // BYTES_PER_MIB, path=disk.path)
        for disk in disks(watched_paths(payload))
        if is_low(disk)
    ]
    if low_space:
        return " ".join([*low_space, FREE_SPACE_NOW, HOW_TO_CLEAN_UP])
    if ran_out_of_space(payload):
        return f"{RAN_OUT} {HOW_TO_CLEAN_UP}"
    return None


def main():
    options = harness_parser().parse_args()
    payload = read_payload()
    cleanup = disk_cleanup(watched_paths(payload))
    notes = " ".join(filter(None, [cleanup, disk_warning(payload)]))
    if notes:
        event = payload.get("hook_event_name")
        write_context(event, notes, options.harness.output_shape)


if __name__ == "__main__":
    run_hook(main)
