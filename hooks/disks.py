import os
import shutil
from collections.abc import Iterable, Iterator
from typing import NamedTuple

BYTES_PER_MIB = 1 << 20


class Disk(NamedTuple):
    path: str
    device: str
    total: int
    free: int

    def has_free_below(self, limit_bytes: int, limit_share: float) -> bool:
        return self.free < min(limit_bytes, self.total * limit_share)


def device_of(path: str) -> str | None:
    try:
        return str(os.stat(path).st_dev)
    except OSError:
        return None


def disks(paths: Iterable[str]) -> Iterator[Disk]:
    seen_devices: set[str] = set()
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


def total_free(disks: Iterable[Disk]) -> int:
    return sum(disk.free for disk in disks)
