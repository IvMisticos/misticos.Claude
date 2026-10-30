import os
import time
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

INSTALL_LOCK = Path.home() / ".local" / "tool-install.pid"
RETRY_SECONDS = 0.2


def take_install_lock() -> bool:
    try:
        descriptor = os.open(INSTALL_LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    with os.fdopen(descriptor, "w") as lock:
        lock.write(f"{os.getpid()}\n")
    return True


def install_lock_holder_is_gone() -> bool:
    try:
        holder = int(INSTALL_LOCK.read_text())
    except OSError:
        return False
    except ValueError:
        return True
    try:
        os.kill(holder, 0)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False
    return False


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
