import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hooks"))

import disk_space
from disk_space import (
    Disk,
    clean_up,
    disk_cleanup,
    forget_recovered_disks,
    needs_cleanup,
    read_free_at_last_cleanup,
    write_free_at_last_cleanup,
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


@pytest.mark.parametrize(("free_gib", "cleans_up"), [(3.6, False), (3.4, True)])
def test_cleans_up_again_after_another_gib_is_used(free_gib, cleans_up):
    free_at_last_cleanup = {"1": int(4.5 * GIB)}
    assert needs_cleanup(disk(250, free_gib), free_at_last_cleanup) == cleans_up


def test_cleans_up_from_scratch_after_the_disk_recovers(tmp_path):
    record = tmp_path / "free.json"
    write_free_at_last_cleanup(record, {"1": GIB // 2, "2": 3 * GIB})
    still_low = Disk("/tmp", "2", 250 * GIB, 2 * GIB)
    disks = [disk(250, 100), still_low]
    forget_recovered_disks(record, disks, read_free_at_last_cleanup(record))
    free_at_last_cleanup = read_free_at_last_cleanup(record)
    assert free_at_last_cleanup == {"2": 3 * GIB}
    assert needs_cleanup(disk(250, 4), free_at_last_cleanup)


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
