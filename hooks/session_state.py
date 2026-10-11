import contextlib
import json
import os
import re
import sys
import time

if sys.platform == "win32":
    import msvcrt
else:
    import fcntl

STATE_ROOT = os.path.expanduser("~/.claude/hooks/data/misticos.Claude")
FORGET_AFTER_SECONDS = 7 * 24 * 60 * 60


def session_file_path(directory, session_id):
    return os.path.join(directory, re.sub(r"[^A-Za-z0-9_-]", "-", session_id))


def forget_stale_files(directory):
    cutoff = time.time() - FORGET_AFTER_SECONDS
    for name in os.listdir(directory):
        path = os.path.join(directory, name)
        try:
            if os.path.getmtime(path) < cutoff:
                os.unlink(path)
        except OSError:
            continue


def lock_exclusively(state_file):
    if sys.platform != "win32":
        fcntl.flock(state_file, fcntl.LOCK_EX)
        return
    state_file.seek(0)
    with contextlib.suppress(OSError):
        msvcrt.locking(state_file.fileno(), msvcrt.LK_LOCK, 1)


@contextlib.contextmanager
def locked_session_file(directory, session_id):
    os.makedirs(directory, exist_ok=True)
    path = session_file_path(directory, session_id)
    if not os.path.exists(path):
        forget_stale_files(directory)
    with open(path, "a+", encoding="utf-8") as state_file:
        lock_exclusively(state_file)
        yield state_file


def read_json(state_file):
    state_file.seek(0)
    try:
        return json.loads(state_file.read())
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None


def write_json(state_file, value):
    state_file.seek(0)
    state_file.truncate()
    json.dump(value, state_file)
