import json
import os
import stat
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import cleanup_policy
import pytest
from cleanup_policy import (
    clean_up_low_disks,
    most_free_since_cleanup,
    needs_cleanup,
    write_most_free_since_cleanup,
)
from disk_space import needs_warning
from disks import Disk

GIB = 1 << 30


def disk(total_gib: float, free_gib: float) -> Disk:
    return Disk("/", "1", int(total_gib * GIB), int(free_gib * GIB))


@pytest.mark.parametrize(
    ("total_gib", "free_gib", "cleans_up"),
    [(250, 4.9, True), (250, 5, False), (4, 1.5, False), (4, 0.9, True)],
)
def test_cleans_up_below_5_gib_or_a_quarter_of_a_small_disk(
    total_gib: float, free_gib: float, cleans_up: bool
) -> None:
    assert needs_cleanup(disk(total_gib, free_gib), {}) == cleans_up


@pytest.mark.parametrize(
    ("total_gib", "free_gib", "warns"),
    [(250, 1.9, True), (250, 2, False), (4, 0.5, False), (4, 0.3, True)],
)
def test_warns_below_2_gib_or_a_tenth_of_a_small_disk(
    total_gib: float, free_gib: float, warns: bool
) -> None:
    assert needs_warning(disk(total_gib, free_gib)) == warns


@pytest.mark.parametrize(
    ("most_free_gib", "free_gib", "cleans_up"),
    [(4.5, 3.6, False), (4.5, 3.4, True), (0.8, 0.5, False), (0.8, 0.3, True)],
)
def test_cleans_up_again_after_another_gib_or_half_the_free_space_is_used(
    most_free_gib: float, free_gib: float, cleans_up: bool
) -> None:
    most_free = {"1": int(most_free_gib * GIB)}
    assert needs_cleanup(disk(250, free_gib), most_free) == cleans_up


@pytest.fixture
def record(tmp_path: Path) -> Path:
    record = tmp_path / "free.json"
    write_most_free_since_cleanup(record, {"1": int(1.5 * GIB), "2": 3 * GIB})
    return record


@pytest.mark.parametrize(
    ("free_gib", "cleans_up"), [(5.3, False), (4.8, False), (4.2, True)]
)
def test_measures_use_from_the_most_free_space_since_cleanup(
    record: Path, free_gib: float, cleans_up: bool
) -> None:
    still_low = Disk("/tmp", "2", 250 * GIB, 2 * GIB)
    most_free_since_cleanup(record, [disk(250, 5.3), still_low])
    most_free = most_free_since_cleanup(record, [disk(250, free_gib), still_low])
    assert most_free == {"1": int(5.3 * GIB), "2": 3 * GIB}
    assert needs_cleanup(disk(250, free_gib), most_free) == cleans_up


def test_a_failed_write_keeps_the_record_whole(
    record: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(source: Path, target: Path) -> None:
        raise OSError

    before = record.read_bytes()
    monkeypatch.setattr(os, "replace", fail)
    write_most_free_since_cleanup(record, {"3": GIB})
    assert record.read_bytes() == before
    assert list(record.parent.iterdir()) == [record]


def test_a_write_never_shows_a_partial_record(
    record: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[bytes] = []
    replace = os.replace

    def peek(source: Path, target: Path) -> None:
        seen.append(record.read_bytes())
        replace(source, target)

    monkeypatch.setattr(os, "replace", peek)
    write_most_free_since_cleanup(record, {"3": GIB})
    assert json.loads(seen[0]) == {"1": int(1.5 * GIB), "2": 3 * GIB}
    assert json.loads(record.read_bytes()) == {"3": GIB}


def test_a_write_keeps_the_mode_of_the_record(record: Path) -> None:
    record.chmod(0o640)
    write_most_free_since_cleanup(record, {"3": GIB})
    assert stat.S_IMODE(record.stat().st_mode) == 0o640


def test_two_concurrent_runs_start_one_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    low = disk(250, 1)

    def slow_disks(paths: object) -> list[Disk]:
        time.sleep(0.1)
        return [low]

    cleanups: list[set[str]] = []

    def count_cleanup(devices: set[str]) -> list[str]:
        cleanups.append(devices)
        return []

    monkeypatch.setattr(cleanup_policy, "disks", slow_disks)
    monkeypatch.setattr(cleanup_policy, "cleared_caches", count_cleanup)
    record = tmp_path / "free.json"
    with ThreadPoolExecutor(2) as pool:
        runs = [pool.submit(clean_up_low_disks, ["/"], record) for _ in range(2)]
        for run in runs:
            run.result()
    assert len(cleanups) == 1
