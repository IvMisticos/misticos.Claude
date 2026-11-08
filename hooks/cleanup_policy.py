import contextlib
import json
from collections.abc import Collection, Generator, Iterable
from pathlib import Path

from atomic_write import write_atomically
from disk_cleanup import cleared_caches
from disks import BYTES_PER_MIB, Disk, disks, total_free
from json_values import json_object_in
from plugin_paths import DATA_ROOT
from session_state import lock_exclusively

CLEAN_UP_BELOW_BYTES = 5 << 30
CLEAN_UP_BELOW_SHARE = 0.25
CLEAN_UP_AGAIN_AFTER_BYTES = 1 << 30
CLEANUP_RECORD = DATA_ROOT / "disk-cleanup.json"


def read_most_free_since_cleanup(record: Path) -> dict[str, int]:
    stored = json_object_in(record)
    return {device: free for device, free in stored.items() if isinstance(free, int)}


def write_most_free_since_cleanup(record: Path, most_free: dict[str, int]) -> None:
    with contextlib.suppress(OSError):
        record.parent.mkdir(parents=True, exist_ok=True)
        write_atomically(record, json.dumps(most_free))


def remember_free_space(record: Path, disks: Iterable[Disk]) -> None:
    free = {disk.device: disk.free for disk in disks}
    write_most_free_since_cleanup(record, read_most_free_since_cleanup(record) | free)


def most_free_since_cleanup(record: Path, disks: Iterable[Disk]) -> dict[str, int]:
    stored = read_most_free_since_cleanup(record)
    free = {disk.device: disk.free for disk in disks}
    updated = {
        device: max(most_free, free.get(device, most_free))
        for device, most_free in stored.items()
    }
    if updated != stored:
        write_most_free_since_cleanup(record, updated)
    return updated


def needs_cleanup(disk: Disk, most_free_since_cleanup: dict[str, int]) -> bool:
    if not disk.has_free_below(CLEAN_UP_BELOW_BYTES, CLEAN_UP_BELOW_SHARE):
        return False
    most_free = most_free_since_cleanup.get(disk.device)
    if most_free is None:
        return True
    return disk.free < most_free - min(CLEAN_UP_AGAIN_AFTER_BYTES, most_free / 2)


@contextlib.contextmanager
def locked_cleanup_record(record: Path) -> Generator[None]:
    record.parent.mkdir(parents=True, exist_ok=True)
    with open(record.with_suffix(".lock"), "a+", encoding="utf-8") as lock:
        lock_exclusively(lock)
        yield


def claim_disks_to_clean(paths: Collection[str], record: Path) -> list[Disk]:
    with locked_cleanup_record(record):
        current = list(disks(paths))
        most_free = most_free_since_cleanup(record, current)
        before = [disk for disk in current if needs_cleanup(disk, most_free)]
        if before:
            remember_free_space(record, before)
        return before


def clean_up_low_disks(
    paths: Collection[str], record: Path = CLEANUP_RECORD
) -> str | None:
    before = claim_disks_to_clean(paths, record)
    if not before:
        return None
    devices = {disk.device for disk in before}
    cleared = cleared_caches(devices)
    after = [disk for disk in disks(paths) if disk.device in devices]
    remember_free_space(record, after)
    freed = max(0, total_free(after) - total_free(before))
    if freed < BYTES_PER_MIB or not cleared:
        return None
    *rest, last = cleared
    caches = f"{', '.join(rest)} and {last}" if rest else last
    return (
        f"Disk space ran low, so the hooks freed {freed // BYTES_PER_MIB} MiB. "
        f"They cleared {caches}."
    )
