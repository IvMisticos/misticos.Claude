import errno
import json
import os
import stat
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import cleanup_policy
import low_space_throttle
import pytest
from cleanup_policy import (
    CLEANUP_LIMIT,
    Cleanup,
    clean_up_low_disks,
)
from disk_space import HOW_TO_CLEAN_UP, NOTE_LIMIT, disk_note, disks_to_note
from disks import BYTES_PER_MIB, Disk
from low_space_throttle import (
    LowSpaceLimit,
    claim_low_disks,
    claim_low_disks_in,
    is_due,
    read_most_free,
    write_most_free,
)

GIB = 1 << 30


def disk(total_gib: float, free_gib: float, device: str = "1") -> Disk:
    return Disk("/", device, int(total_gib * GIB), int(free_gib * GIB))


@pytest.mark.parametrize(
    ("limit", "total_gib", "free_gib", "due"),
    [
        (CLEANUP_LIMIT, 250, 4.9, True),
        (CLEANUP_LIMIT, 250, 5, False),
        (CLEANUP_LIMIT, 4, 1.5, False),
        (CLEANUP_LIMIT, 4, 0.9, True),
        (NOTE_LIMIT, 250, 1.9, True),
        (NOTE_LIMIT, 250, 2, False),
        (NOTE_LIMIT, 4, 0.5, False),
        (NOTE_LIMIT, 4, 0.3, True),
    ],
)
def test_is_due_below_a_size_or_a_share_of_a_small_disk(
    limit: LowSpaceLimit, total_gib: float, free_gib: float, due: bool
) -> None:
    assert is_due(disk(total_gib, free_gib), {}, limit) == due


@pytest.mark.parametrize(
    ("most_free_gib", "free_gib", "due"),
    [(4.5, 3.6, False), (4.5, 3.4, True), (0.8, 0.5, False), (0.8, 0.3, True)],
)
def test_is_due_again_after_another_gib_or_half_the_free_space_is_used(
    most_free_gib: float, free_gib: float, due: bool
) -> None:
    most_free = {"1": int(most_free_gib * GIB)}
    assert is_due(disk(250, free_gib), most_free, CLEANUP_LIMIT) == due


@pytest.mark.parametrize(("free_gib", "due"), [(5.3, False), (4.8, False), (4.2, True)])
def test_measures_use_from_the_most_free_space_since_the_last_claim(
    free_gib: float, due: bool
) -> None:
    still_low = disk(250, 2, device="2")
    stored = {"1": int(1.5 * GIB), "2": 3 * GIB}
    raised = claim_low_disks(stored, [disk(250, 5.3), still_low], CLEANUP_LIMIT)
    claim = claim_low_disks(
        raised.most_free, [disk(250, free_gib), still_low], CLEANUP_LIMIT
    )
    assert claim.due == ([disk(250, free_gib)] if due else [])
    assert claim.most_free["2"] == 3 * GIB


@pytest.fixture
def record(tmp_path: Path) -> Path:
    record = tmp_path / "free.json"
    write_most_free(record, {"1": int(1.5 * GIB), "2": 3 * GIB})
    return record


def test_a_failed_write_keeps_the_record_whole(
    record: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(source: Path, target: Path) -> None:
        raise OSError

    before = record.read_bytes()
    monkeypatch.setattr(os, "replace", fail)
    write_most_free(record, {"3": GIB})
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
    write_most_free(record, {"3": GIB})
    assert json.loads(seen[0]) == {"1": int(1.5 * GIB), "2": 3 * GIB}
    assert json.loads(record.read_bytes()) == {"3": GIB}


def test_a_write_keeps_the_mode_of_the_record(record: Path) -> None:
    record.chmod(0o640)
    write_most_free(record, {"3": GIB})
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


def test_a_cleanup_reports_what_it_freed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    free = [disk(250, 4), disk(250, 6)]
    monkeypatch.setattr(cleanup_policy, "disks", lambda paths: [free.pop(0)])
    monkeypatch.setattr(cleanup_policy, "cleared_caches", lambda devices: ["x"])
    record = tmp_path / "free.json"
    assert clean_up_low_disks(["/"], record) == Cleanup(2 * GIB, ["x"])
    assert read_most_free(record) == {"1": 6 * GIB}


@pytest.fixture
def notes_dir(tmp_path: Path) -> Path:
    return tmp_path / "disk-notes"


def test_a_session_hears_once_until_free_space_drops_again(notes_dir: Path) -> None:
    assert disks_to_note("main", [disk(250, 1.5)], notes_dir) == [disk(250, 1.5)]
    assert disks_to_note("main", [disk(250, 1.5)], notes_dir) == []
    assert disks_to_note("main", [disk(250, 1)], notes_dir) == []
    assert disks_to_note("main", [disk(250, 0.7)], notes_dir) == [disk(250, 0.7)]


def test_a_second_session_on_an_unchanged_low_disk_hears_too(notes_dir: Path) -> None:
    disks_to_note("first", [disk(250, 1.5)], notes_dir)
    assert disks_to_note("second", [disk(250, 1.5)], notes_dir) == [disk(250, 1.5)]


def test_a_subagent_note_leaves_the_main_agent_note(notes_dir: Path) -> None:
    disks_to_note("session-agent", [disk(250, 1.5)], notes_dir)
    assert disks_to_note("session", [disk(250, 1.5)], notes_dir) == [disk(250, 1.5)]


def test_a_full_disk_is_noted_once_per_session(notes_dir: Path) -> None:
    full = disk(250, 0)
    assert disks_to_note("first", [full], notes_dir) == [full]
    assert disks_to_note("first", [full], notes_dir) == []
    assert disks_to_note("second", [full], notes_dir) == [full]


def test_a_claimed_cleanup_leaves_the_session_note_due(
    tmp_path: Path, notes_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    claim_low_disks_in(tmp_path / "free.json", [disk(250, 1.5)], CLEANUP_LIMIT)
    assert disks_to_note("main", [disk(250, 1.5)], notes_dir) == [disk(250, 1.5)]


def test_a_record_that_cannot_be_written_still_yields_the_note(
    notes_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def disk_full(path: Path, text: str) -> None:
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(low_space_throttle, "write_atomically", disk_full)
    full = disk(250, 0)
    assert disks_to_note("main", [full], notes_dir) == [full]
    assert disks_to_note("main", [full], notes_dir) == [full]


def test_a_lock_that_cannot_be_created_still_yields_the_note(
    notes_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def disk_full(self: Path, *args: object, **kwargs: object) -> None:
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(Path, "mkdir", disk_full)
    assert disks_to_note("main", [disk(250, 0)], notes_dir) == [disk(250, 0)]


def test_stale_session_records_are_forgotten(notes_dir: Path) -> None:
    disks_to_note("old", [disk(250, 1.5)], notes_dir)
    for stale in notes_dir.iterdir():
        os.utime(stale, (0, 0))
    disks_to_note("new", [disk(250, 1.5)], notes_dir)
    assert sorted(path.name for path in notes_dir.iterdir()) == [
        "new.json",
        "new.lock",
    ]


def test_the_note_says_what_the_hooks_freed_and_what_to_free() -> None:
    caches = ["the NuGet HTTP cache", "dangling Docker images"]
    cleanup = Cleanup(300 * BYTES_PER_MIB, caches)
    assert disk_note(cleanup, [disk(250, 1)]) == (
        "Disk space ran low, so the hooks freed 300 MiB: they cleared the NuGet "
        "HTTP cache and dangling Docker images. Only 1024 MiB of disk is free at "
        f"/, so free 1024 MiB more there. {HOW_TO_CLEAN_UP}"
    )


def test_the_note_without_a_cleanup_says_what_to_free() -> None:
    assert disk_note(None, [disk(250, 0.5)]) == (
        "Only 512 MiB of disk is free at /, so free 1536 MiB more there. "
        f"{HOW_TO_CLEAN_UP}"
    )


def test_the_note_only_reports_the_freed_space_when_no_disk_is_due() -> None:
    cleanup = Cleanup(2 * GIB, ["the NuGet HTTP cache"])
    assert disk_note(cleanup, []) == (
        "Disk space ran low, so the hooks freed 2048 MiB: they cleared the NuGet "
        "HTTP cache."
    )


def test_a_cleanup_that_freed_nothing_and_no_due_disk_says_nothing() -> None:
    assert disk_note(Cleanup(0, []), []) is None
