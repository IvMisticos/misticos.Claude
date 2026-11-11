#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# [tool.ty.environment]
# root = ["."]
# ///

import contextlib
import math
import os
from collections.abc import Iterable
from pathlib import Path

from cleanup_policy import Cleanup, clean_up_low_disks
from disks import BYTES_PER_MIB, Disk, disks
from harnesses import harness_parser
from hook_io import (
    agent_session_key,
    cwd_of,
    event_name_of,
    read_payload,
    run_hook,
    scratchpad_of,
    write_context,
)
from json_values import JsonObject
from low_space_throttle import LowSpaceLimit, claim_low_disks_in
from plugin_paths import DATA_ROOT
from session_state import forget_stale_files, session_file_path

NOTE_LIMIT = LowSpaceLimit(2 << 30, 0.1)
DISK_NOTES_DIR = DATA_ROOT / "disk-notes"
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


def session_record(notes_dir: Path, agent_key: str) -> Path:
    return Path(session_file_path(notes_dir, agent_key)).with_suffix(".json")


def disks_to_note(
    agent_key: str, current: Iterable[Disk], notes_dir: Path = DISK_NOTES_DIR
) -> list[Disk]:
    record = session_record(notes_dir, agent_key)
    if not record.exists():
        with contextlib.suppress(OSError):
            forget_stale_files(notes_dir)
    return claim_low_disks_in(record, current, NOTE_LIMIT)


def in_words(items: list[str]) -> str:
    *rest, last = items
    return f"{', '.join(rest)} and {last}" if rest else last


def freed_note(cleanup: Cleanup | None) -> list[str]:
    if cleanup is None or cleanup.freed < BYTES_PER_MIB or not cleanup.cleared:
        return []
    freed = cleanup.freed // BYTES_PER_MIB
    return [HOOKS_FREED.format(freed=freed, caches=in_words(cleanup.cleared))]


def still_low_note(disk: Disk) -> str:
    return STILL_LOW.format(
        free=disk.free // BYTES_PER_MIB,
        path=disk.path,
        needed=math.ceil(NOTE_LIMIT.space_to_free(disk) / BYTES_PER_MIB),
    )


def disk_note(cleanup: Cleanup | None, low_disks: list[Disk]) -> str | None:
    still_low = [still_low_note(disk) for disk in low_disks]
    how_to = [HOW_TO_CLEAN_UP] if still_low else []
    note = " ".join([*freed_note(cleanup), *still_low, *how_to])
    return note or None


def main() -> None:
    options = harness_parser().parse_args()
    payload = read_payload()
    paths = watched_paths(payload)
    cleanup = clean_up_low_disks(paths)
    agent_key = agent_session_key(payload)
    low_disks = disks_to_note(agent_key, disks(paths)) if agent_key else []
    note = disk_note(cleanup, low_disks)
    if note:
        write_context(event_name_of(payload), note, options.harness.output_shape)


if __name__ == "__main__":
    run_hook(main)
