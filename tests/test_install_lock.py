import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hooks"))

import install_lock


@pytest.fixture
def lock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    lock = tmp_path / "tool-install.pid"
    monkeypatch.setattr(install_lock, "INSTALL_LOCK", lock)
    return lock


def age(path: Path, seconds: float) -> None:
    then = time.time() - seconds
    os.utime(path, (then, then))


def test_a_fresh_empty_lock_is_still_held(lock: Path) -> None:
    lock.write_text("")
    assert not install_lock.install_lock_holder_is_gone()


def test_an_old_empty_lock_is_abandoned(lock: Path) -> None:
    lock.write_text("")
    age(lock, install_lock.ABANDONED_EMPTY_LOCK_SECONDS + 1)
    assert install_lock.install_lock_holder_is_gone()


def test_a_garbled_lock_is_abandoned(lock: Path) -> None:
    lock.write_text("not a pid\n")
    assert install_lock.install_lock_holder_is_gone()


def test_a_lock_of_a_live_process_is_held(lock: Path) -> None:
    lock.write_text(f"{os.getpid()}\n")
    assert not install_lock.install_lock_holder_is_gone()
