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
SCRATCH_FOLDER_NOTE = (
    "Put clones, downloads and other temporary files in {folder}. It can be "
    "deleted as soon as you finish responding, before your caller reads your "
    "answer, so put anything you hand back somewhere else."
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


def other_tasks_in_flight(payload):
    tasks = payload.get("background_tasks")
    if not isinstance(tasks, list):
        return None
    agent_id = payload.get("agent_id")
    return [task for task in tasks if not is_task(task, agent_id)]


def is_task(task, task_id):
    return isinstance(task, dict) and task.get("id") == task_id


def offer_agent_folder(payload):
    folder = agent_folder(payload)
    if not folder:
        return
    folder.mkdir(parents=True, exist_ok=True)
    note = SCRATCH_FOLDER_NOTE.format(folder=folder)
    json.dump(hook_output("SubagentStart", note, "claude"), sys.stdout)


def delete_agent_folder(payload):
    folder = agent_folder(payload)
    if folder and other_tasks_in_flight(payload) == []:
        shutil.rmtree(folder, ignore_errors=True)


def delete_every_agent_folder(payload):
    root = agent_folders_root(payload)
    if root:
        shutil.rmtree(root, ignore_errors=True)


def delete_every_idle_agent_folder(payload):
    if payload.get("background_tasks") == []:
        delete_every_agent_folder(payload)


HANDLERS = {
    "SubagentStart": offer_agent_folder,
    "SubagentStop": delete_agent_folder,
    "Stop": delete_every_idle_agent_folder,
    "SessionEnd": delete_every_agent_folder,
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
