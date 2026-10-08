import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hooks"))

import disk_space
from disk_space import (
    Disk,
    clean_up,
    disk_cleanup,
    most_free_since_cleanup,
    needs_cleanup,
    write_most_free_since_cleanup,
)

GIB = 1 << 30


def disk(total_gib, free_gib):
    return Disk("/", "1", int(total_gib * GIB), int(free_gib * GIB))


@pytest.mark.parametrize(
    ("total_gib", "free_gib", "cleans_up"),
    [(250, 4.9, True), (250, 5, False), (4, 1.5, False), (4, 0.9, True)],
)
def test_cleans_up_below_5_gib_or_a_quarter_of_a_small_disk(
    total_gib, free_gib, cleans_up
):
    assert needs_cleanup(disk(total_gib, free_gib), {}) == cleans_up


@pytest.mark.parametrize(
    ("most_free_gib", "free_gib", "cleans_up"),
    [(4.5, 3.6, False), (4.5, 3.4, True), (0.8, 0.5, False), (0.8, 0.3, True)],
)
def test_cleans_up_again_after_another_gib_or_half_the_free_space_is_used(
    most_free_gib, free_gib, cleans_up
):
    most_free = {"1": int(most_free_gib * GIB)}
    assert needs_cleanup(disk(250, free_gib), most_free) == cleans_up


@pytest.fixture
def record(tmp_path):
    record = tmp_path / "free.json"
    write_most_free_since_cleanup(record, {"1": int(1.5 * GIB), "2": 3 * GIB})
    return record


@pytest.mark.parametrize(
    ("free_gib", "cleans_up"), [(5.3, False), (4.8, False), (4.2, True)]
)
def test_measures_use_from_the_most_free_space_since_cleanup(
    record, free_gib, cleans_up
):
    still_low = Disk("/tmp", "2", 250 * GIB, 2 * GIB)
    most_free_since_cleanup(record, [disk(250, 5.3), still_low])
    most_free = most_free_since_cleanup(record, [disk(250, free_gib), still_low])
    assert most_free == {"1": int(5.3 * GIB), "2": 3 * GIB}
    assert needs_cleanup(disk(250, free_gib), most_free) == cleans_up


def add_build_output(scratchpad):
    (scratchpad / "app" / "bin").mkdir(parents=True)
    (scratchpad / "app" / "App.csproj").write_text("x")


@pytest.fixture
def scratchpad(tmp_path, monkeypatch):
    monkeypatch.setattr(disk_space, "cleared_caches", lambda devices: [])
    add_build_output(tmp_path)
    return tmp_path


@pytest.fixture
def full_disks(monkeypatch):
    monkeypatch.setattr(disk_space, "CLEAN_UP_BELOW_BYTES", 1 << 62)
    monkeypatch.setattr(disk_space, "CLEAN_UP_BELOW_SHARE", 2)


def clean_up_scratchpad(scratchpad):
    device = disk_space.device_of(scratchpad)
    return clean_up([str(scratchpad)], {device}, str(scratchpad))


def test_keeps_build_output_when_clearing_caches_freed_enough(scratchpad, monkeypatch):
    monkeypatch.setattr(disk_space, "CLEAN_UP_BELOW_BYTES", 0)
    assert clean_up_scratchpad(scratchpad).build_output == []
    assert (scratchpad / "app" / "bin").exists()


def test_deletes_build_output_when_the_disk_still_needs_space(scratchpad, full_disks):
    assert clean_up_scratchpad(scratchpad).build_output == [scratchpad / "app" / "bin"]


def test_each_session_cleans_up_its_own_scratchpad(scratchpad, full_disks):
    sessions = [scratchpad / "a", scratchpad / "b"]
    for session in sessions:
        add_build_output(session)
    for session in sessions:
        disk_cleanup({"cwd": str(session), "scratchpad_dir": str(session)})
    assert not any((session / "app" / "bin").exists() for session in sessions)
