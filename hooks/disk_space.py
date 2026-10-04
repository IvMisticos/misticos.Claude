#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///

import json
import os
import re
import shutil
import sys
import tempfile
import traceback

from reminder import QuietArgumentParser, hook_output

LOW_SPACE_BYTES = 1 << 30
BYTES_PER_MIB = 1 << 20
OUT_OF_SPACE_ERROR = re.compile(
    r"\bENOSPC\b|\bEDQUOT\b|(?i:no space left on device|disk quota exceeded"
    r"|not enough space on the disk|database or disk is full)"
)
READ_ONLY_TOOLS = {"Read", "Grep", "Glob", "LS", "WebFetch", "WebSearch"}
TOOL_RESULT_FIELDS = ("tool_response", "tool_output", "error_message")
RAN_OUT = "A tool call ran out of disk space."
RUNNING_LOW = "Only {free} MiB of disk is free at {path}."
CLEAN_UP = (
    "Free space now: delete build output, package caches and clones you no "
    "longer need. Keep the uv cache: the hooks run from it. Delete only what "
    "you created or can regenerate."
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
    return (cwd, tempfile.gettempdir(), os.path.expanduser("~"))


def low_disks(paths):
    seen_devices = set()
    for path in paths:
        try:
            device = os.stat(path).st_dev
            free = shutil.disk_usage(path).free
        except OSError:
            continue
        if device in seen_devices:
            continue
        seen_devices.add(device)
        if free < LOW_SPACE_BYTES:
            yield path, free


def warning_causes(payload):
    if ran_out_of_space(payload):
        yield RAN_OUT
    for path, free in low_disks(watched_paths(payload)):
        yield RUNNING_LOW.format(free=free // BYTES_PER_MIB, path=path)


def disk_warning(payload):
    causes = list(warning_causes(payload))
    return " ".join([*causes, CLEAN_UP]) if causes else None


def parsed_options(argv):
    parser = QuietArgumentParser(add_help=False)
    parser.add_argument(
        "--output-shape", choices=("claude", "cursor"), default="claude"
    )
    return parser.parse_args(argv)


def main():
    options = parsed_options(sys.argv[1:])
    payload = json.loads(sys.stdin.read() or "{}")
    warning = disk_warning(payload)
    if warning:
        event = payload.get("hook_event_name")
        json.dump(hook_output(event, warning, options.output_shape), sys.stdout)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(0)
