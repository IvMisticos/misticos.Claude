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
from pathlib import Path
from typing import NamedTuple

from disk_cleanup import cleared_caches, device_of
from harnesses import add_harness_argument
from hook_io import QuietArgumentParser, hook_output, read_payload, run_hook

LOW_SPACE_BYTES = 1 << 30
LOW_SPACE_SHARE = 0.1
BYTES_PER_MIB = 1 << 20
CLEAN_UP_BELOW_BYTES = 5 << 30
CLEAN_UP_BELOW_SHARE = 0.25
CLEAN_UP_AGAIN_AFTER_BYTES = 1 << 30
CLEANUP_RECORD = (
    Path.home() / ".claude" / "hooks" / "data" / "misticos.Claude" / "disk-cleanup.json"
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
CLEANED_UP = "Disk space ran low, so the hooks freed {freed} MiB."
CLEARED_CACHES = "They cleared {caches}."
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


class Disk(NamedTuple):
    path: str
    device: str
    total: int
    free: int


def disks(paths):
    seen_devices = set()
    for path in paths:
        device = device_of(path)
        if device is None or device in seen_devices:
            continue
        try:
            usage = shutil.disk_usage(path)
        except OSError:
            continue
        seen_devices.add(device)
        yield Disk(path, device, usage.total, usage.free)


def low_disks(paths):
    return ((disk.path, disk.free) for disk in disks(paths) if is_low(disk))


def total_free(disks):
    return sum(disk.free for disk in disks)


def read_most_free_since_cleanup(record):
    try:
        stored = json.loads(record.read_text())
    except (OSError, ValueError):
        return {}
    if not isinstance(stored, dict):
        return {}
    return {device: free for device, free in stored.items() if isinstance(free, int)}


def write_most_free_since_cleanup(record, most_free):
    with contextlib.suppress(OSError):
        record.parent.mkdir(parents=True, exist_ok=True)
        record.write_text(json.dumps(most_free))


def remember_free_space(record, disks):
    free = {disk.device: disk.free for disk in disks}
    write_most_free_since_cleanup(record, read_most_free_since_cleanup(record) | free)


def most_free_since_cleanup(record, disks):
    stored = read_most_free_since_cleanup(record)
    free = {disk.device: disk.free for disk in disks}
    updated = {
        device: max(most_free, free.get(device, most_free))
        for device, most_free in stored.items()
    }
    if updated != stored:
        write_most_free_since_cleanup(record, updated)
    return updated


def cleanup_threshold(disk):
    return min(CLEAN_UP_BELOW_BYTES, disk.total * CLEAN_UP_BELOW_SHARE)


def needs_space(disk):
    return disk.free < cleanup_threshold(disk)


def cleanup_step(most_free):
    return min(CLEAN_UP_AGAIN_AFTER_BYTES, most_free / 2)


def needs_cleanup(disk, most_free_since_cleanup):
    if not needs_space(disk):
        return False
    most_free = most_free_since_cleanup.get(disk.device)
    return most_free is None or disk.free < most_free - cleanup_step(most_free)


def scratchpad_of(payload):
    scratchpad = payload.get("scratchpad_dir")
    if isinstance(scratchpad, str) and os.path.isabs(scratchpad):
        return scratchpad
    return None


def listed(items):
    *rest, last = items
    return f"{', '.join(rest)} and {last}" if rest else last


def cleanup_report(cleared, freed):
    freed_mib = CLEANED_UP.format(freed=freed // BYTES_PER_MIB)
    return f"{freed_mib} {CLEARED_CACHES.format(caches=listed(cleared))}"


def disk_cleanup(payload):
    paths = watched_paths(payload)
    current = list(disks(paths))
    most_free = most_free_since_cleanup(CLEANUP_RECORD, current)
    before = [disk for disk in current if needs_cleanup(disk, most_free)]
    if not before:
        return None
    remember_free_space(CLEANUP_RECORD, before)
    devices = {disk.device for disk in before}
    cleared = cleared_caches(devices)
    after = [disk for disk in disks(paths) if disk.device in devices]
    remember_free_space(CLEANUP_RECORD, after)
    freed = max(0, total_free(after) - total_free(before))
    if freed < BYTES_PER_MIB or not cleared:
        return None
    return cleanup_report(cleared, freed)


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
    add_harness_argument(parser)
    return parser.parse_args(argv)


def disk_notes(payload):
    notes = filter(None, [disk_cleanup(payload), disk_warning(payload)])
    return " ".join(notes)


def main():
    options = parsed_options(sys.argv[1:])
    payload = read_payload()
    notes = disk_notes(payload)
    if notes:
        event = payload.get("hook_event_name")
        json.dump(
            hook_output(event, notes, options.harness.output_shape),
            sys.stdout,
        )


if __name__ == "__main__":
    run_hook(main)
