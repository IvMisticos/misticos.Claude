#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///

import json
import os
import re
import shutil
import sys
import traceback
from pathlib import Path

from reminder import hook_output

AGENT_ID = re.compile(r"[A-Za-z0-9_-]+")
TASKS_THAT_MAY_USE_THE_FOLDER = {"shell", "monitor"}
SCRATCH_FOLDER_NOTE = (
    "Put clones, downloads and other temporary files in {folder}. It can be "
    "deleted whenever you finish responding, so keep nothing there that you "
    "need later."
)


def agent_folders_root(payload):
    scratchpad = payload.get("scratchpad_dir")
    if isinstance(scratchpad, str) and os.path.isabs(scratchpad):
        return Path(scratchpad) / "agents"
    return None


def agent_folder(payload):
    root = agent_folders_root(payload)
    agent_id = payload.get("agent_id")
    if root and isinstance(agent_id, str) and AGENT_ID.fullmatch(agent_id):
        return root / agent_id
    return None


def in_flight_task_types(payload):
    tasks = payload.get("background_tasks")
    if not isinstance(tasks, list):
        return None
    return {task.get("type") for task in tasks if isinstance(task, dict)}


def offer_agent_folder(payload):
    folder = agent_folder(payload)
    if not folder:
        return
    folder.mkdir(parents=True, exist_ok=True)
    note = SCRATCH_FOLDER_NOTE.format(folder=folder)
    json.dump(hook_output("SubagentStart", note, "claude"), sys.stdout)


def delete_agent_folder(payload):
    folder = agent_folder(payload)
    task_types = in_flight_task_types(payload)
    if not folder or task_types is None:
        return
    if task_types.isdisjoint(TASKS_THAT_MAY_USE_THE_FOLDER):
        shutil.rmtree(folder, ignore_errors=True)


def delete_every_agent_folder(payload):
    root = agent_folders_root(payload)
    if root and payload.get("background_tasks") == []:
        shutil.rmtree(root, ignore_errors=True)


HANDLERS = {
    "SubagentStart": offer_agent_folder,
    "SubagentStop": delete_agent_folder,
    "Stop": delete_every_agent_folder,
}


def main():
    payload = json.loads(sys.stdin.read() or "{}")
    handle = HANDLERS.get(payload.get("hook_event_name"))
    if handle:
        handle(payload)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(0)
