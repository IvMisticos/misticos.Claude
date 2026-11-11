from collections.abc import Collection
from pathlib import Path
from typing import NamedTuple

from disk_cleanup import cleared_caches
from disks import disks, total_free
from low_space_throttle import LowSpaceLimit, claim_low_disks_in, raise_most_free_in
from plugin_paths import DATA_ROOT

CLEANUP_LIMIT = LowSpaceLimit(5 << 30, 0.25)
CLEANUP_RECORD = DATA_ROOT / "disk-cleanup.json"


class Cleanup(NamedTuple):
    freed: int
    cleared: list[str]


def clean_up_low_disks(
    paths: Collection[str], record: Path = CLEANUP_RECORD
) -> Cleanup | None:
    lock_path = record.with_suffix(".lock")
    before = claim_low_disks_in(record, lock_path, disks(paths), CLEANUP_LIMIT)
    if not before:
        return None
    devices = {disk.device for disk in before}
    cleared = cleared_caches(devices)
    after = [disk for disk in disks(paths) if disk.device in devices]
    raise_most_free_in(record, lock_path, after)
    freed = max(0, total_free(after) - total_free(before))
    return Cleanup(freed, cleared)
