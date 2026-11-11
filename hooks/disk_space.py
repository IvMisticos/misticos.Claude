#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# [tool.ty.environment]
# root = ["."]
# ///

import math
import os

from cleanup_policy import Cleanup, clean_up_low_disks, space_to_free
from disks import BYTES_PER_MIB, Disk
from harnesses import harness_parser
from hook_io import (
    cwd_of,
    event_name_of,
    read_payload,
    run_hook,
    scratchpad_of,
    write_context,
)
from json_values import JsonObject

TEMP_DIR_VARIABLES = ("TMPDIR", "TEMP", "TMP")
HOOKS_FREED = (
    "Disk space ran low, so the hooks freed {freed} MiB: they cleared {caches}."
)
STILL_LOW = (
    "Only {free} MiB of disk is free at {path}, so free {needed} MiB more there."
)
HOW_TO_CLEAN_UP = (
    "Delete build output, package caches and clones you no longer need. Keep "
    "the uv cache: the hooks run from it. Delete only what you created or can "
    "regenerate."
)


def watched_paths(payload: JsonObject) -> tuple[str, ...]:
    cwd = cwd_of(payload)
    temp_dirs = filter(None, map(os.environ.get, TEMP_DIR_VARIABLES))
    scratchpad = filter(None, [scratchpad_of(payload)])
    return (cwd, os.path.expanduser("~"), *temp_dirs, "/tmp", *scratchpad)


def in_words(items: list[str]) -> str:
    *rest, last = items
    return f"{', '.join(rest)} and {last}" if rest else last


def freed_note(cleanup: Cleanup) -> list[str]:
    if cleanup.freed < BYTES_PER_MIB or not cleanup.cleared:
        return []
    freed = cleanup.freed // BYTES_PER_MIB
    return [HOOKS_FREED.format(freed=freed, caches=in_words(cleanup.cleared))]


def still_low_note(disk: Disk) -> str:
    return STILL_LOW.format(
        free=disk.free // BYTES_PER_MIB,
        path=disk.path,
        needed=math.ceil(space_to_free(disk) / BYTES_PER_MIB),
    )


def disk_note(cleanup: Cleanup) -> str | None:
    still_low = [still_low_note(disk) for disk in cleanup.low_disks]
    how_to = [HOW_TO_CLEAN_UP] if still_low else []
    note = " ".join([*freed_note(cleanup), *still_low, *how_to])
    return note or None


def main() -> None:
    options = harness_parser().parse_args()
    payload = read_payload()
    cleanup = clean_up_low_disks(watched_paths(payload))
    if cleanup is None:
        return
    note = disk_note(cleanup)
    if note:
        write_context(event_name_of(payload), note, options.harness.output_shape)


if __name__ == "__main__":
    run_hook(main)
