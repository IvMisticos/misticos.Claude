import os
import shutil
from typing import NamedTuple

BYTES_PER_MIB = 1 << 20


class Disk(NamedTuple):
    path: str
    device: str
    total: int
    free: int


def device_of(path):
    try:
        return str(os.stat(path).st_dev)
    except OSError:
        return None


def disks(paths):
    seen_devices = set()
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


def total_free(disks):
    return sum(disk.free for disk in disks)
