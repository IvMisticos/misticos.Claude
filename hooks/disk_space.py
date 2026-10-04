#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///

import json
import os
import re
import shutil
import sys
import traceback

from reminder import QuietArgumentParser, hook_output

LOW_SPACE_BYTES = 1 << 30
BYTES_PER_MIB = 1 << 20
OUT_OF_SPACE_ERROR = re.compile(
    r"no space left on device|disk quota exceeded|not enough space on the disk",
    re.IGNORECASE,
)
TOOL_RESULT_FIELDS = ("tool_response", "tool_output", "error_message")
RAN_OUT = "A tool call ran out of disk space."
RUNNING_LOW = "Only {free} MiB of disk is free at {path}."
CLEAN_UP = (
    "Free space now: delete build output, caches and clones you no longer "
    "need. Delete only what you created or can regenerate."
)


def tool_results(payload):
    calls = [payload, *(payload.get("tool_calls") or [])]
    return (
        json.dumps(call.get(field))
        for call in calls
        if isinstance(call, dict)
        for field in TOOL_RESULT_FIELDS
    )


def ran_out_of_space(payload):
    return any(OUT_OF_SPACE_ERROR.search(result) for result in tool_results(payload))


def free_bytes(path):
    try:
        return shutil.disk_usage(path).free
    except OSError:
        return None


def warning_causes(payload):
    if ran_out_of_space(payload):
        yield RAN_OUT
    path = payload.get("cwd") or os.getcwd()
    free = free_bytes(path)
    if free is not None and free < LOW_SPACE_BYTES:
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
