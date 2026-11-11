import contextlib
import json
from collections.abc import Collection, Generator, Iterable
from pathlib import Path
from typing import NamedTuple

from atomic_write import write_atomically
from disk_cleanup import cleared_caches
from disks import Disk, disks, total_free
from json_values import json_object_in
from low_space_throttle import (
    LowSpaceLimit,
    MostFree,
    claim_low_disks,
    parsed_most_free,
    raised_most_free,
)
from plugin_paths import DATA_ROOT
from session_state import lock_exclusively

CLEANUP_LIMIT = LowSpaceLimit(5 << 30, 0.25)
CLEANUP_RECORD = DATA_ROOT / "disk-cleanup.json"


class Cleanup(NamedTuple):
    freed: int
    cleared: list[str]


def read_most_free_since_cleanup(record: Path) -> MostFree:
    return parsed_most_free(json_object_in(record))


def write_most_free_since_cleanup(record: Path, most_free: MostFree) -> None:
    with contextlib.suppress(OSError):
        record.parent.mkdir(parents=True, exist_ok=True)
        write_atomically(record, json.dumps(most_free))


@contextlib.contextmanager
def locked_cleanup_record(record: Path) -> Generator[None]:
    record.parent.mkdir(parents=True, exist_ok=True)
    with open(record.with_suffix(".lock"), "a+", encoding="utf-8") as lock:
        lock_exclusively(lock)
        yield


def claim_disks_to_clean(paths: Collection[str], record: Path) -> list[Disk]:
    with locked_cleanup_record(record):
        stored = read_most_free_since_cleanup(record)
        claim = claim_low_disks(stored, disks(paths), CLEANUP_LIMIT)
        if claim.most_free != stored:
            write_most_free_since_cleanup(record, claim.most_free)
        return claim.due


def remember_free_space(record: Path, disks: Iterable[Disk]) -> None:
    with locked_cleanup_record(record):
        stored = read_most_free_since_cleanup(record)
        raised = raised_most_free(stored, disks)
        if raised != stored:
            write_most_free_since_cleanup(record, raised)


def clean_up_low_disks(
    paths: Collection[str], record: Path = CLEANUP_RECORD
) -> Cleanup | None:
    before = claim_disks_to_clean(paths, record)
    if not before:
        return None
    devices = {disk.device for disk in before}
    cleared = cleared_caches(devices)
    after = [disk for disk in disks(paths) if disk.device in devices]
    remember_free_space(record, after)
    freed = max(0, total_free(after) - total_free(before))
    return Cleanup(freed, cleared)
