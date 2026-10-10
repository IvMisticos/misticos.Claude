#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from hook_io import hook_output, read_payload, run_hook

AGENT_ID = re.compile(r"[A-Za-z0-9_-]+")
ENDS_WITH_TASKS_RUNNING = {"clear", "resume"}
DELETE_FOLDER = "import shutil, sys; shutil.rmtree(sys.argv[1], ignore_errors=True)"
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


def delete_in_background(folder):
    subprocess.Popen(
        [sys.executable, "-c", DELETE_FOLDER, str(folder)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def delete_agent_folders_after_session(payload):
    root = agent_folders_root(payload)
    if not root or payload.get("reason") in ENDS_WITH_TASKS_RUNNING:
        return
    trash = root.with_name(f"{root.name}-deleted-{os.getpid()}")
    try:
        root.rename(trash)
    except OSError:
        return
    delete_in_background(trash)


HANDLERS = {
    "SubagentStart": offer_agent_folder,
    "SubagentStop": delete_agent_folder,
    "Stop": delete_every_idle_agent_folder,
    "SessionEnd": delete_agent_folders_after_session,
}


def main():
    payload = read_payload()
    handle = HANDLERS.get(payload.get("hook_event_name"))
    if handle:
        handle(payload)


if __name__ == "__main__":
    run_hook(main)
