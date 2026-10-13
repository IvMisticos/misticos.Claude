import fcntl
from contextlib import contextmanager
from pathlib import Path

SETTINGS_LOCK = Path.home() / ".claude" / "settings.lock"


@contextmanager
def holding_settings_lock():
    SETTINGS_LOCK.parent.mkdir(parents=True, exist_ok=True)
    with SETTINGS_LOCK.open("a") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        yield
