#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# [tool.ty.environment]
# root = ["."]
# ///

import os
import re
import subprocess
import sys
from pathlib import Path

from harnesses import OutputShape
from hook_io import (
    event_name_of,
    read_payload,
    run_hook,
    scratchpad_of,
    write_block,
    write_context,
)
from json_values import JsonObject, JsonValue
from review_thread_reminder import review_reminder

AGENT_ID = re.compile(r"[A-Za-z0-9_-]+")
ENDS_WITH_TASKS_RUNNING = {"clear", "resume"}
DELETE_FOLDER = "import shutil, sys; shutil.rmtree(sys.argv[1], ignore_errors=True)"
SCRATCH_FOLDER_NOTE = (
    "Put clones, downloads and other temporary files in {folder}. It can be "
    "deleted as soon as you finish responding, before your caller reads your "
    "answer, so put anything you hand back somewhere else."
)


def agent_folders_root(payload: JsonObject) -> Path | None:
    scratchpad = scratchpad_of(payload)
    return Path(scratchpad) / "agents" if scratchpad else None


def agent_folder(payload: JsonObject) -> Path | None:
    root = agent_folders_root(payload)
    agent_id = payload.get("agent_id")
    if root and isinstance(agent_id, str) and AGENT_ID.fullmatch(agent_id):
        return root / agent_id
    return None


def other_tasks_in_flight(payload: JsonObject) -> list[JsonValue] | None:
    tasks = payload.get("background_tasks")
    if not isinstance(tasks, list):
        return None
    agent_id = payload.get("agent_id")
    return [
        task
        for task in tasks
        if not (isinstance(task, dict) and task.get("id") == agent_id)
    ]


def offer_agent_folder(payload: JsonObject) -> None:
    folder = agent_folder(payload)
    if not folder:
        return
    folder.mkdir(parents=True, exist_ok=True)
    note = SCRATCH_FOLDER_NOTE.format(folder=folder)
    write_context("SubagentStart", note, OutputShape.CLAUDE)


def delete_in_background(folder: Path) -> None:
    subprocess.Popen(
        [sys.executable, "-c", DELETE_FOLDER, str(folder)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def delete_soon(folder: Path) -> None:
    trash = folder.with_name(f"{folder.name}-deleted-{os.getpid()}")
    try:
        folder.rename(trash)
    except OSError:
        return
    delete_in_background(trash)


def delete_agent_folder(payload: JsonObject) -> None:
    folder = agent_folder(payload)
    if folder and other_tasks_in_flight(payload) == []:
        delete_soon(folder)


def finish_agent(payload: JsonObject) -> None:
    reason = review_reminder(payload)
    if reason:
        write_block(reason, OutputShape.CLAUDE)
        return
    delete_agent_folder(payload)


def delete_agent_folders_when_idle(payload: JsonObject) -> None:
    root = agent_folders_root(payload)
    if root and payload.get("background_tasks") == []:
        delete_soon(root)


def delete_agent_folders_after_session(payload: JsonObject) -> None:
    root = agent_folders_root(payload)
    if root and payload.get("reason") not in ENDS_WITH_TASKS_RUNNING:
        delete_soon(root)


HANDLERS = {
    "SubagentStart": offer_agent_folder,
    "SubagentStop": finish_agent,
    "Stop": delete_agent_folders_when_idle,
    "SessionEnd": delete_agent_folders_after_session,
}


def main() -> None:
    payload = read_payload()
    handle = HANDLERS.get(event_name_of(payload))
    if handle:
        handle(payload)


if __name__ == "__main__":
    run_hook(main)
