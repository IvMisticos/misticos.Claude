import json
import os
import stat
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import cleanup_policy
import pytest
from cleanup_policy import (
    Cleanup,
    clean_up_low_disks,
    most_free_since_cleanup,
    needs_cleanup,
    write_most_free_since_cleanup,
)
from disk_space import HOW_TO_CLEAN_UP, disk_note
from disks import BYTES_PER_MIB, Disk

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


def run_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    record: Path,
    free_gib: float,
    freed_gib: float = 0,
) -> Cleanup | None:
    free = [disk(250, free_gib), disk(250, free_gib + freed_gib)]
    monkeypatch.setattr(cleanup_policy, "disks", lambda paths: [free.pop(0)])
    monkeypatch.setattr(cleanup_policy, "cleared_caches", lambda devices: [])
    return clean_up_low_disks(["/"], record)


def test_a_disk_that_stays_low_is_reported_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = tmp_path / "free.json"
    first = run_cleanup(monkeypatch, record, 1.5)
    assert first is not None
    assert first.low_disks == [disk(250, 1.5)]
    assert run_cleanup(monkeypatch, record, 1.4) is None
    assert run_cleanup(monkeypatch, record, 0.7) is not None


def test_a_cleanup_that_frees_enough_reports_no_low_disk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cleanup = run_cleanup(monkeypatch, tmp_path / "free.json", 4, freed_gib=2)
    assert cleanup == Cleanup(2 * GIB, [], [])


def test_the_note_says_what_the_hooks_freed_and_what_to_free() -> None:
    caches = ["the NuGet HTTP cache", "dangling Docker images"]
    cleanup = Cleanup(300 * BYTES_PER_MIB, caches, [disk(250, 1)])
    assert disk_note(cleanup) == (
        "Disk space ran low, so the hooks freed 300 MiB: they cleared the NuGet "
        "HTTP cache and dangling Docker images. Only 1024 MiB of disk is free at "
        f"/, so free 4096 MiB more there. {HOW_TO_CLEAN_UP}"
    )


def test_the_note_only_reports_the_freed_space_when_the_disk_recovered() -> None:
    cleanup = Cleanup(2 * GIB, ["the NuGet HTTP cache"], [])
    assert disk_note(cleanup) == (
        "Disk space ran low, so the hooks freed 2048 MiB: they cleared the NuGet "
        "HTTP cache."
    )


def test_a_cleanup_that_freed_nothing_and_left_enough_space_says_nothing() -> None:
    assert disk_note(Cleanup(0, [], [])) is None
