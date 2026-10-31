import os
import time
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

INSTALL_LOCK = Path.home() / ".local" / "tool-install.pid"
RETRY_SECONDS = 0.2
ABANDONED_EMPTY_LOCK_SECONDS = 5


def take_install_lock() -> bool:
    try:
        descriptor = os.open(INSTALL_LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    with os.fdopen(descriptor, "w") as lock:
        lock.write(f"{os.getpid()}\n")
    return True


def install_lock_is_old() -> bool:
    try:
        modified = INSTALL_LOCK.stat().st_mtime
    except OSError:
        return False
    return time.time() - modified >= ABANDONED_EMPTY_LOCK_SECONDS


def process_is_gone(process_id: int) -> bool:
    try:
        os.kill(process_id, 0)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False
    return False


def install_lock_holder_is_gone() -> bool:
    try:
        holder = INSTALL_LOCK.read_text().strip()
    except OSError:
        return False
    if not holder:
        return install_lock_is_old()
    try:
        return process_is_gone(int(holder))
    except ValueError:
        return True


@contextmanager
def install_lock() -> Generator[None]:
    INSTALL_LOCK.parent.mkdir(parents=True, exist_ok=True)
    while not take_install_lock():
        if install_lock_holder_is_gone():
            INSTALL_LOCK.unlink(missing_ok=True)
        time.sleep(RETRY_SECONDS)
    try:
        yield
    finally:
        INSTALL_LOCK.unlink(missing_ok=True)
