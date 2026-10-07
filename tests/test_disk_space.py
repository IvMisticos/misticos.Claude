import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hooks"))

from disk_space import Disk, needs_cleanup

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
