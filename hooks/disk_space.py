#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///

import contextlib
import json
import os
import re
import shutil
import sys
import time
import traceback
from pathlib import Path

from disk_cleanup import clean_up
from reminder import QuietArgumentParser, hook_output

LOW_SPACE_BYTES = 1 << 30
LOW_SPACE_SHARE = 0.1
BYTES_PER_MIB = 1 << 20
CLEAN_UP_BELOW_BYTES = 5 << 30
CLEAN_UP_AT_MOST_EVERY_SECONDS = 5 * 60
CLEANUP_STAMP = (
    Path.home() / ".claude" / "hooks" / "data" / "misticos.Claude" / "disk-cleanup"
)
OUT_OF_SPACE_ERROR = re.compile(
    r"no space left on device|disk quota exceeded|not enough space on the disk"
    r"|database or disk is full",
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
CLEANED_UP = "Free disk space fell under 5 GiB, so the hooks freed {freed} MiB."
CLEARED_CACHES = "They cleared {caches}."
DELETED_BUILD_OUTPUT = (
    "They deleted {count} build output folders named {names} under "
    "{scratchpad}. Rebuild or reinstall before you use them."
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
    return (cwd, os.path.expanduser("~"), *temp_dirs, "/tmp")


def is_low(usage):
    return usage.free < min(LOW_SPACE_BYTES, usage.total * LOW_SPACE_SHARE)


def disk_usages(paths):
    seen_devices = set()
    for path in paths:
        try:
            device = os.stat(path).st_dev
            usage = shutil.disk_usage(path)
        except OSError:
            continue
        if device in seen_devices:
            continue
        seen_devices.add(device)
        yield path, usage


def low_disks(paths):
    return ((path, usage.free) for path, usage in disk_usages(paths) if is_low(usage))


def free_bytes(paths):
    return sum(usage.free for _, usage in disk_usages(paths))


def needs_cleanup(paths):
    return any(usage.free < CLEAN_UP_BELOW_BYTES for _, usage in disk_usages(paths))


def cleanup_is_due():
    try:
        cleaned_at = CLEANUP_STAMP.stat().st_mtime
    except OSError:
        return True
    return time.time() - cleaned_at >= CLEAN_UP_AT_MOST_EVERY_SECONDS


def mark_cleanup_started():
    with contextlib.suppress(OSError):
        CLEANUP_STAMP.parent.mkdir(parents=True, exist_ok=True)
        CLEANUP_STAMP.touch()


def scratchpad_of(payload):
    scratchpad = payload.get("scratchpad_dir")
    if isinstance(scratchpad, str) and os.path.isabs(scratchpad):
        return scratchpad
    return None


def listed(items):
    *rest, last = items
    return f"{', '.join(rest)} and {last}" if rest else last


def deleted_build_output_note(folders, scratchpad):
    names = listed(sorted({folder.name for folder in folders}))
    count = len(folders)
    return DELETED_BUILD_OUTPUT.format(count=count, names=names, scratchpad=scratchpad)


def cleanup_report(cleanup, freed, scratchpad):
    report = [CLEANED_UP.format(freed=freed // BYTES_PER_MIB)]
    if cleanup.cleared_caches:
        report.append(CLEARED_CACHES.format(caches=listed(cleanup.cleared_caches)))
    if cleanup.build_output:
        report.append(deleted_build_output_note(cleanup.build_output, scratchpad))
    return " ".join(report)


def disk_cleanup(payload):
    paths = watched_paths(payload)
    if not (needs_cleanup(paths) and cleanup_is_due()):
        return None
    mark_cleanup_started()
    scratchpad = scratchpad_of(payload)
    free_before = free_bytes(paths)
    cleanup = clean_up(scratchpad)
    if not (cleanup.cleared_caches or cleanup.build_output):
        return None
    freed = max(0, free_bytes(paths) - free_before)
    return cleanup_report(cleanup, freed, scratchpad)


def disk_warning(payload):
    low_space = [
        RUNNING_LOW.format(free=free // BYTES_PER_MIB, path=path)
        for path, free in low_disks(watched_paths(payload))
    ]
    if low_space:
        return " ".join([*low_space, FREE_SPACE_NOW, HOW_TO_CLEAN_UP])
    if ran_out_of_space(payload):
        return f"{RAN_OUT} {HOW_TO_CLEAN_UP}"
    return None


def parsed_options(argv):
    parser = QuietArgumentParser(add_help=False)
    parser.add_argument(
        "--output-shape", choices=("claude", "cursor"), default="claude"
    )
    return parser.parse_args(argv)


def disk_notes(payload):
    notes = filter(None, [disk_cleanup(payload), disk_warning(payload)])
    return " ".join(notes)


def main():
    options = parsed_options(sys.argv[1:])
    payload = json.loads(sys.stdin.read() or "{}")
    notes = disk_notes(payload)
    if notes:
        event = payload.get("hook_event_name")
        json.dump(hook_output(event, notes, options.output_shape), sys.stdout)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(0)
