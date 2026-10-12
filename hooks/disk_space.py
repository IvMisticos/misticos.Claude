#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///

import os

from cleanup_policy import disk_cleanup
from disks import BYTES_PER_MIB, disks
from harnesses import harness_parser
from hook_io import (
    cwd_of,
    event_name_of,
    read_payload,
    run_hook,
    scratchpad_of,
    write_context,
)

LOW_SPACE_BYTES = 1 << 30
LOW_SPACE_SHARE = 0.1
TEMP_DIR_VARIABLES = ("TMPDIR", "TEMP", "TMP")
RUNNING_LOW = "Only {free} MiB of disk is free at {path}."
FREE_SPACE_NOW = "Free space now."
HOW_TO_CLEAN_UP = (
    "Delete build output, package caches and clones you no longer need. Keep "
    "the uv cache: the hooks run from it. Delete only what you created or can "
    "regenerate."
)


def watched_paths(payload):
    cwd = cwd_of(payload)
    temp_dirs = filter(None, map(os.environ.get, TEMP_DIR_VARIABLES))
    scratchpad = filter(None, [scratchpad_of(payload)])
    return (cwd, os.path.expanduser("~"), *temp_dirs, "/tmp", *scratchpad)


def disk_warning(payload):
    low_space = [
        RUNNING_LOW.format(free=disk.free // BYTES_PER_MIB, path=disk.path)
        for disk in disks(watched_paths(payload))
        if disk.has_free_below(LOW_SPACE_BYTES, LOW_SPACE_SHARE)
    ]
    if low_space:
        return " ".join([*low_space, FREE_SPACE_NOW, HOW_TO_CLEAN_UP])
    return None


def main():
    options = harness_parser().parse_args()
    payload = read_payload()
    cleanup = disk_cleanup(watched_paths(payload))
    notes = " ".join(filter(None, [cleanup, disk_warning(payload)]))
    if notes:
        write_context(event_name_of(payload), notes, options.harness.output_shape)


if __name__ == "__main__":
    run_hook(main)
