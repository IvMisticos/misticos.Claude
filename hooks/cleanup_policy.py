import contextlib
import json
from pathlib import Path

from disk_cleanup import cleared_caches
from disks import BYTES_PER_MIB, disks, total_free

CLEAN_UP_BELOW_BYTES = 5 << 30
CLEAN_UP_BELOW_SHARE = 0.25
CLEAN_UP_AGAIN_AFTER_BYTES = 1 << 30
CLEANUP_RECORD = (
    Path.home() / ".claude" / "hooks" / "data" / "misticos.Claude" / "disk-cleanup.json"
)


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


def needs_cleanup(disk, most_free_since_cleanup):
    if disk.free >= min(CLEAN_UP_BELOW_BYTES, disk.total * CLEAN_UP_BELOW_SHARE):
        return False
    most_free = most_free_since_cleanup.get(disk.device)
    if most_free is None:
        return True
    return disk.free < most_free - min(CLEAN_UP_AGAIN_AFTER_BYTES, most_free / 2)


def disk_cleanup(paths):
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
    *rest, last = cleared
    caches = f"{', '.join(rest)} and {last}" if rest else last
    return (
        f"Disk space ran low, so the hooks freed {freed // BYTES_PER_MIB} MiB. "
        f"They cleared {caches}."
    )
