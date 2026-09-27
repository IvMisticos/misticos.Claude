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


def layer_role(folder, role_name):
    declared = declared_role_file(folder, role_name)
    if declared:
        return read_toml(declared)
    roles = map(read_toml, discovered_role_files(folder))
    return next((role for role in roles if role.get("name") == role_name), {})


def role_model(role_name, cwd):
    layer_models = (
        layer_role(folder, role_name).get("model") for folder in config_folders(cwd)
    )
    return next((model for model in layer_models if model), None)


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
    role_name = spawn.get("agent_type")
    fixed_model = role_model(role_name, cwd) if role_name else None
    if outranks(fixed_model, caller):
        return {
            "permissionDecision": "deny",
            "permissionDecisionReason": (
                f"The {role_name} role runs on {fixed_model}, above your {caller}. "
                "Spawn with a role at or below your model, or with no agent_type."
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
