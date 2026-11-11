from collections.abc import Iterable
from typing import NamedTuple

from disks import Disk
from json_values import JsonValue

AGAIN_AFTER_BYTES = 1 << 30

type MostFree = dict[str, int]


class LowSpaceLimit(NamedTuple):
    limit_bytes: int
    limit_share: float

    def space_to_free(self, disk: Disk) -> int:
        limit = int(min(self.limit_bytes, disk.total * self.limit_share))
        return max(0, limit - disk.free)


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
