#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///

import glob
import json
import os
import sys
import tomllib
from pathlib import Path

from model_tiers import outranks

DEFAULT_ROLE = "default"


def read_toml(path):
    try:
        with open(path, "rb") as toml_file:
            return tomllib.load(toml_file)
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def config_folders(cwd):
    project_folders = [
        folder / ".codex"
        for folder in (Path(cwd), *Path(cwd).parents)
        if (folder / ".codex").is_dir()
    ]
    user_folder = Path(os.environ.get("CODEX_HOME") or "~/.codex").expanduser()
    return [*project_folders, user_folder]


def agents_table(folder):
    agents = read_toml(folder / "config.toml").get("agents")
    return agents if isinstance(agents, dict) else {}


def declared_role_file(folder, role_name):
    role = agents_table(folder).get(role_name)
    config_file = role.get("config_file") if isinstance(role, dict) else None
    return folder / config_file if config_file else None


def discovered_role_files(folder):
    pattern = str(folder / "agents" / "**" / "*.toml")
    return map(Path, glob.glob(pattern, recursive=True))


def layer_role_file(folder, role_name):
    declared = declared_role_file(folder, role_name)
    if declared:
        return declared
    return next(
        (
            role_file
            for role_file in discovered_role_files(folder)
            if read_toml(role_file).get("name") == role_name
        ),
        None,
    )


def role_model(role_name, cwd):
    role_files = (layer_role_file(folder, role_name) for folder in config_folders(cwd))
    role_file = next((role_file for role_file in role_files if role_file), None)
    return read_toml(role_file).get("model") if role_file else None


def default_subagent_model(cwd):
    for folder in config_folders(cwd):
        model = agents_table(folder).get("default_subagent_model")
        if model:
            return model
    return None


def hook_output(decision):
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", **decision}}


def cap_decision(payload):
    caller = payload.get("model")
    spawn = payload.get("tool_input") or {}
    cwd = payload.get("cwd") or os.getcwd()
    role_name = str(spawn.get("agent_type") or "").strip() or DEFAULT_ROLE
    fixed_model = role_model(role_name, cwd)
    if outranks(fixed_model, caller):
        return {
            "permissionDecision": "deny",
            "permissionDecisionReason": (
                f"The {role_name} role runs on {fixed_model}, above your {caller}. "
                "Spawn with a role at or below your model."
            ),
        }
    requested = spawn.get("model") or default_subagent_model(cwd)
    if not outranks(requested, caller):
        return None
    return {"permissionDecision": "allow", "updatedInput": {**spawn, "model": caller}}


def main():
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        return
    decision = cap_decision(payload)
    if decision:
        json.dump(hook_output(decision), sys.stdout)


if __name__ == "__main__":
    main()
