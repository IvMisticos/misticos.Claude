#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///

import glob
import os
import tomllib
from pathlib import Path

from hook_io import run_pre_tool_use
from model_cap import outranks, project_folders

DEFAULT_ROLE = "default"


def read_toml(path):
    try:
        with open(path, "rb") as toml_file:
            return tomllib.load(toml_file)
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def config_folders(cwd):
    project_layers = [
        folder / ".codex"
        for folder in project_folders(Path(cwd))
        if (folder / ".codex").is_dir()
    ]
    user_layer = Path(os.environ.get("CODEX_HOME") or "~/.codex").expanduser()
    return [*project_layers, user_layer]


def agents_table(folder):
    agents = read_toml(folder / "config.toml").get("agents")
    return agents if isinstance(agents, dict) else {}


def declared_role_files(folder):
    for table_key, role in agents_table(folder).items():
        config_file = role.get("config_file") if isinstance(role, dict) else None
        if config_file and (folder / config_file).is_file():
            yield table_key, folder / config_file


def discovered_role_files(folder):
    pattern = str(folder / "agents" / "**" / "*.toml")
    return map(Path, glob.glob(pattern, recursive=True))


def layer_roles(folder):
    roles = {}
    declared_files = set()
    for table_key, role_file in declared_role_files(folder):
        declared_files.add(role_file.resolve())
        roles.setdefault(read_toml(role_file).get("name") or table_key, role_file)
    for role_file in discovered_role_files(folder):
        role_name = read_toml(role_file).get("name")
        if role_name and role_file.resolve() not in declared_files:
            roles.setdefault(role_name, role_file)
    return roles


def role_model(role_name, cwd):
    role_files = (layer_roles(folder).get(role_name) for folder in config_folders(cwd))
    role_file = next((role_file for role_file in role_files if role_file), None)
    return read_toml(role_file).get("model") if role_file else None


def default_subagent_model(cwd):
    for folder in config_folders(cwd):
        model = agents_table(folder).get("default_subagent_model")
        if model:
            return model
    return None


def forks_full_history(spawn, is_v2):
    if not is_v2:
        return spawn.get("fork_context") is True
    fork_turns = str(spawn.get("fork_turns") or "").strip().lower()
    return fork_turns in ("", "all")


def applies_role(spawn, named_role):
    is_v2 = "task_name" in spawn
    if not forks_full_history(spawn, is_v2):
        return True
    return is_v2 and bool(named_role)


def cap_decision(payload):
    caller = payload.get("model")
    spawn = payload.get("tool_input") or {}
    cwd = payload.get("cwd") or os.getcwd()
    named_role = str(spawn.get("agent_type") or "").strip()
    role_name = named_role or DEFAULT_ROLE
    fixed_model = (
        role_model(role_name, cwd) if applies_role(spawn, named_role) else None
    )
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


if __name__ == "__main__":
    run_pre_tool_use(cap_decision)
