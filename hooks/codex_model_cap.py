#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///

import glob
import os
import tomllib
from pathlib import Path
from typing import NamedTuple

from hook_io import allowed_with, denied, run_pre_tool_use
from model_cap import outranks, project_folders

DEFAULT_ROLE = "default"


class RoleFile(NamedTuple):
    name: str | None
    model: str | None


class CodexLayer(NamedTuple):
    role_models: dict[str, str | None]
    default_subagent_model: str | None


def read_toml(path):
    try:
        with open(path, "rb") as toml_file:
            return tomllib.load(toml_file)
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def text_or_none(value):
    return value if isinstance(value, str) and value else None


def parsed_role_file(path):
    table = read_toml(path)
    return RoleFile(text_or_none(table.get("name")), text_or_none(table.get("model")))


def config_folders(cwd):
    project_layers = [
        folder / ".codex"
        for folder in project_folders(Path(cwd))
        if (folder / ".codex").is_dir()
    ]
    user_layer = Path(os.environ.get("CODEX_HOME") or "~/.codex").expanduser()
    return [*project_layers, user_layer]


def declared_role_files(folder, agents):
    for table_key, role in agents.items():
        config_file = role.get("config_file") if isinstance(role, dict) else None
        if isinstance(config_file, str) and (folder / config_file).is_file():
            yield table_key, folder / config_file


def discovered_role_files(folder):
    pattern = str(folder / "agents" / "**" / "*.toml")
    return map(Path, glob.glob(pattern, recursive=True))


def layer_role_models(folder, agents):
    role_models = {}
    declared_files = set()
    for table_key, role_file in declared_role_files(folder, agents):
        declared_files.add(role_file.resolve())
        role = parsed_role_file(role_file)
        role_models.setdefault(role.name or table_key, role.model)
    for role_file in discovered_role_files(folder):
        if role_file.resolve() in declared_files:
            continue
        role = parsed_role_file(role_file)
        if role.name:
            role_models.setdefault(role.name, role.model)
    return role_models


def parsed_layer(folder):
    agents = read_toml(folder / "config.toml").get("agents")
    agents = agents if isinstance(agents, dict) else {}
    default_model = text_or_none(agents.get("default_subagent_model"))
    return CodexLayer(layer_role_models(folder, agents), default_model)


def codex_layers(cwd):
    return [parsed_layer(folder) for folder in config_folders(cwd)]


def role_model(role_name, layers):
    models = (layer.role_models for layer in layers if role_name in layer.role_models)
    return next(models, {}).get(role_name)


def default_subagent_model(layers):
    models = (layer.default_subagent_model for layer in layers)
    return next(filter(None, models), None)


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


def role_decision(spawn, layers, caller):
    named_role = str(spawn.get("agent_type") or "").strip()
    role_name = named_role or DEFAULT_ROLE
    fixed_model = (
        role_model(role_name, layers) if applies_role(spawn, named_role) else None
    )
    if not outranks(fixed_model, caller):
        return None
    return denied(
        f"The {role_name} role runs on {fixed_model}, above your {caller}. "
        "Spawn with a role at or below your model."
    )


def request_decision(spawn, layers, caller):
    requested = spawn.get("model") or default_subagent_model(layers)
    if not outranks(requested, caller):
        return None
    return allowed_with({**spawn, "model": caller})


def cap_decision(payload):
    caller = payload.get("model")
    spawn = payload.get("tool_input") or {}
    layers = codex_layers(payload.get("cwd") or os.getcwd())
    return role_decision(spawn, layers, caller) or request_decision(
        spawn, layers, caller
    )


if __name__ == "__main__":
    run_pre_tool_use(cap_decision)
