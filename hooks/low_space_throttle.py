import contextlib
import json
from collections.abc import Generator, Iterable
from pathlib import Path
from typing import NamedTuple

from atomic_write import write_atomically
from disks import Disk
from json_values import JsonValue, json_object_in
from session_state import lock_exclusively

AGAIN_AFTER_BYTES = 1 << 30

type MostFree = dict[str, int]


class LowSpaceLimit(NamedTuple):
    limit_bytes: int
    limit_share: float

    def space_to_free(self, disk: Disk) -> int:
        limit = int(min(self.limit_bytes, disk.total * self.limit_share))
        return max(0, limit - disk.free)

    def has_low(self, disks: Iterable[Disk]) -> bool:
        return any(self.space_to_free(disk) for disk in disks)


class Claim(NamedTuple):
    due: list[Disk]
    most_free: MostFree


def parsed_most_free(stored: JsonValue) -> MostFree:
    if not isinstance(stored, dict):
        return {}
    return {device: free for device, free in stored.items() if isinstance(free, int)}


def raised_most_free(most_free: MostFree, disks: Iterable[Disk]) -> MostFree:
    free = {disk.device: disk.free for disk in disks}
    return {
        device: max(most_free, free.get(device, most_free))
        for device, most_free in most_free.items()
    }


def is_due(disk: Disk, most_free: MostFree, limit: LowSpaceLimit) -> bool:
    if not limit.space_to_free(disk):
        return False
    previous = most_free.get(disk.device)
    if previous is None:
        return True
    return disk.free < previous - min(AGAIN_AFTER_BYTES, previous / 2)


def claim_low_disks(
    most_free: MostFree, disks: Iterable[Disk], limit: LowSpaceLimit
) -> Claim:
    current = list(disks)
    raised = raised_most_free(most_free, current)
    due = [disk for disk in current if is_due(disk, raised, limit)]
    return Claim(due, raised | {disk.device: disk.free for disk in due})


def read_most_free(record: Path) -> MostFree:
    return parsed_most_free(json_object_in(record))


def write_most_free(record: Path, most_free: MostFree) -> None:
    with contextlib.suppress(OSError):
        record.parent.mkdir(parents=True, exist_ok=True)
        write_atomically(record, json.dumps(most_free))


@contextlib.contextmanager
def locked(lock_path: Path) -> Generator[None]:
    with contextlib.ExitStack() as stack:
        with contextlib.suppress(OSError):
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            lock = stack.enter_context(open(lock_path, "a+", encoding="utf-8"))
            lock_exclusively(lock)
        yield


def raise_most_free_in(record: Path, lock_path: Path, disks: Iterable[Disk]) -> None:
    current = list(disks)
    unlocked = read_most_free(record)
    if raised_most_free(unlocked, current) == unlocked:
        return
    with locked(lock_path):
        stored = read_most_free(record)
        raised = raised_most_free(stored, current)
        if raised != stored:
            write_most_free(record, raised)


def claim_low_disks_in(
    record: Path, lock_path: Path, disks: Iterable[Disk], limit: LowSpaceLimit
) -> list[Disk]:
    current = list(disks)
    if not limit.has_low(current):
        raise_most_free_in(record, lock_path, current)
        return []
    with locked(lock_path):
        stored = read_most_free(record)
        claim = claim_low_disks(stored, current, limit)
        if claim.most_free != stored:
            write_most_free(record, claim.most_free)
        return claim.due
