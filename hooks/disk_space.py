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
import traceback
from pathlib import Path
from typing import NamedTuple

from disk_cleanup import clean_up, device_of
from reminder import QuietArgumentParser, hook_output

LOW_SPACE_BYTES = 1 << 30
LOW_SPACE_SHARE = 0.1
BYTES_PER_MIB = 1 << 20
CLEAN_UP_BELOW_BYTES = 5 << 30
CLEAN_UP_BELOW_SHARE = 0.25
CLEAN_UP_AGAIN_AFTER_BYTES = 1 << 30
FREE_AT_LAST_CLEANUP = (
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
DELETED_BUILD_OUTPUT = (
    "They deleted the {names} build output under {scratchpad}. Rebuild or "
    "reinstall before you use it."
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


def read_free_at_last_cleanup():
    try:
        stored = json.loads(FREE_AT_LAST_CLEANUP.read_text())
    except (OSError, ValueError):
        return {}
    if not isinstance(stored, dict):
        return {}
    return {device: free for device, free in stored.items() if isinstance(free, int)}


def write_free_at_last_cleanup(free):
    with contextlib.suppress(OSError):
        FREE_AT_LAST_CLEANUP.parent.mkdir(parents=True, exist_ok=True)
        FREE_AT_LAST_CLEANUP.write_text(json.dumps(free))


def remember_free_space(disks):
    free = {disk.device: disk.free for disk in disks}
    write_free_at_last_cleanup(read_free_at_last_cleanup() | free)


def forget_recovered_disks(disks, free_at_last_cleanup):
    recovered = {disk.device for disk in disks if not needs_space(disk)}
    if recovered & free_at_last_cleanup.keys():
        records = free_at_last_cleanup.items()
        kept = {device: free for device, free in records if device not in recovered}
        write_free_at_last_cleanup(kept)


def cleanup_threshold(disk):
    return min(CLEAN_UP_BELOW_BYTES, disk.total * CLEAN_UP_BELOW_SHARE)


def needs_space(disk):
    return disk.free < cleanup_threshold(disk)


def needs_cleanup(disk, free_at_last_cleanup):
    if not needs_space(disk):
        return False
    last_free = free_at_last_cleanup.get(disk.device)
    return last_free is None or disk.free < last_free - CLEAN_UP_AGAIN_AFTER_BYTES


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
    return DELETED_BUILD_OUTPUT.format(names=names, scratchpad=scratchpad)


def cleanup_report(cleanup, freed, scratchpad):
    report = [CLEANED_UP.format(freed=freed // BYTES_PER_MIB)]
    if cleanup.cleared_caches:
        report.append(CLEARED_CACHES.format(caches=listed(cleanup.cleared_caches)))
    if cleanup.build_output:
        report.append(deleted_build_output_note(cleanup.build_output, scratchpad))
    return " ".join(report)


def disk_cleanup(payload):
    paths = watched_paths(payload)
    current = list(disks(paths))
    free_at_last_cleanup = read_free_at_last_cleanup()
    forget_recovered_disks(current, free_at_last_cleanup)
    before = [disk for disk in current if needs_cleanup(disk, free_at_last_cleanup)]
    if not before:
        return None
    remember_free_space(before)
    devices = {disk.device for disk in before}
    scratchpad = scratchpad_of(payload)
    cleanup = clean_up(scratchpad, devices)
    after = [disk for disk in disks(paths) if disk.device in devices]
    remember_free_space(after)
    if not (cleanup.cleared_caches or cleanup.build_output):
        return None
    freed = max(0, total_free(after) - total_free(before))
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
