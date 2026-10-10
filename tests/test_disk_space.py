import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hooks"))

from cleanup_policy import (
    most_free_since_cleanup,
    needs_cleanup,
    write_most_free_since_cleanup,
)
from disks import Disk

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
