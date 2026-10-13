#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# [tool.ty.environment]
# root = ["."]
# ///

import glob
import os
import tomllib
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import NamedTuple

from hook_io import (
    PreToolUseDecision,
    allowed_with,
    cwd_of,
    denied,
    run_pre_tool_use,
)
from json_values import JsonObject, JsonValue, dict_or_empty
from model_cap import outranks, project_folders

DEFAULT_ROLE = "default"


class RoleFile(NamedTuple):
    name: str | None
    model: str | None


class CodexLayer(NamedTuple):
    folder: Path
    declared_role_files: dict[str, Path]
    default_subagent_model: str | None


def read_toml(path: Path) -> dict[str, object]:
    try:
        with open(path, "rb") as toml_file:
            return tomllib.load(toml_file)
    except (OSError, ValueError):
        return {}


def text_or_none(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def parsed_role_file(path: Path) -> RoleFile:
    table = read_toml(path)
    return RoleFile(text_or_none(table.get("name")), text_or_none(table.get("model")))


def config_folders(cwd: str) -> list[Path]:
    project_layers = [
        folder / ".codex"
        for folder in project_folders(Path(cwd))
        if (folder / ".codex").is_dir()
    ]
    user_layer = Path(os.environ.get("CODEX_HOME") or "~/.codex").expanduser()
    return [*project_layers, user_layer]


def declared_role_files(folder: Path, agents: dict[str, object]) -> dict[str, Path]:
    declared: dict[str, Path] = {}
    for table_key, role in agents.items():
        config_file = role.get("config_file") if isinstance(role, dict) else None
        if isinstance(config_file, str) and (folder / config_file).is_file():
            declared[table_key] = folder / config_file
    return declared


def discovered_role_files(folder: Path) -> Iterator[Path]:
    pattern = str(folder / "agents" / "**" / "*.toml")
    return map(Path, glob.glob(pattern, recursive=True))


def layer_role_models(layer: CodexLayer) -> dict[str, str | None]:
    role_models: dict[str, str | None] = {}
    declared_files: set[Path] = set()
    for table_key, role_file in layer.declared_role_files.items():
        declared_files.add(role_file.resolve())
        role = parsed_role_file(role_file)
        role_models.setdefault(role.name or table_key, role.model)
    for role_file in discovered_role_files(layer.folder):
        if role_file.resolve() in declared_files:
            continue
        role = parsed_role_file(role_file)
        if role.name:
            role_models.setdefault(role.name, role.model)
    return role_models


def parsed_layer(folder: Path) -> CodexLayer:
    agents = read_toml(folder / "config.toml").get("agents")
    agents = agents if isinstance(agents, dict) else {}
    default_model = text_or_none(agents.get("default_subagent_model"))
    return CodexLayer(folder, declared_role_files(folder, agents), default_model)


def codex_layers(cwd: str) -> list[CodexLayer]:
    return [parsed_layer(folder) for folder in config_folders(cwd)]


def role_model(role_name: str, layers: Iterable[CodexLayer]) -> str | None:
    for layer in layers:
        role_models = layer_role_models(layer)
        if role_name in role_models:
            return role_models[role_name]
    return None


def default_subagent_model(layers: Iterable[CodexLayer]) -> str | None:
    models = (layer.default_subagent_model for layer in layers)
    return next(filter(None, models), None)


def forks_full_history(spawn: JsonObject, is_v2: bool) -> bool:
    if not is_v2:
        return spawn.get("fork_context") is True
    fork_turns = str(spawn.get("fork_turns") or "").strip().lower()
    return fork_turns in ("", "all")


def applies_role(spawn: JsonObject, named_role: str) -> bool:
    is_v2 = "task_name" in spawn
    if not forks_full_history(spawn, is_v2):
        return True
    return is_v2 and bool(named_role)


def role_decision(
    spawn: JsonObject, layers: list[CodexLayer], caller: JsonValue
) -> PreToolUseDecision | None:
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


def request_decision(
    spawn: JsonObject, layers: list[CodexLayer], caller: JsonValue
) -> PreToolUseDecision | None:
    requested = spawn.get("model") or default_subagent_model(layers)
    if not outranks(requested, caller):
        return None
    return allowed_with({**spawn, "model": caller})


def cap_decision(payload: JsonObject) -> PreToolUseDecision | None:
    caller = payload.get("model")
    spawn = dict_or_empty(payload.get("tool_input"))
    layers = codex_layers(cwd_of(payload))
    return role_decision(spawn, layers, caller) or request_decision(
        spawn, layers, caller
    )


if __name__ == "__main__":
    run_pre_tool_use(cap_decision)
