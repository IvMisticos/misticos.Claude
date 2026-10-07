#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# ///

import contextlib
import json
import os
import re
import shutil
import stat
import sys
import traceback
from pathlib import Path

from reminder import hook_output

AGENT_ID = re.compile(r"[A-Za-z0-9_-]+")
SCRATCH_FOLDER_NOTE = (
    "Put clones, downloads and other temporary files in {folder}. It is "
    "deleted each time you finish responding, so keep nothing there that you "
    "need later."
)


def agent_scratch_folder(payload):
    scratchpad = payload.get("scratchpad_dir")
    agent_id = payload.get("agent_id")
    if not (isinstance(scratchpad, str) and isinstance(agent_id, str)):
        return None
    if not (os.path.isabs(scratchpad) and AGENT_ID.fullmatch(agent_id)):
        return None
    return Path(scratchpad) / agent_id


def offer_scratch_folder(folder):
    folder.mkdir(parents=True, exist_ok=True)
    note = SCRATCH_FOLDER_NOTE.format(folder=folder)
    json.dump(hook_output("SubagentStart", note, "claude"), sys.stdout)


def delete_read_only_entry(remove, path, _error):
    with contextlib.suppress(OSError):
        os.chmod(path, os.lstat(path).st_mode | stat.S_IWRITE)
        remove(path)


def delete_scratch_folder(folder):
    if folder.is_dir():
        shutil.rmtree(folder, onexc=delete_read_only_entry)


HANDLERS = {
    "SubagentStart": offer_scratch_folder,
    "SubagentStop": delete_scratch_folder,
}


def main():
    payload = json.loads(sys.stdin.read() or "{}")
    folder = agent_scratch_folder(payload)
    handle = HANDLERS.get(payload.get("hook_event_name"))
    if folder and handle:
        handle(folder)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(0)
