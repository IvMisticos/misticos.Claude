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
from json_values import JsonObject, dict_or_empty, text_or_none
from model_cap import (
    Model,
    capped_input,
    config_folders,
    denial_reason,
    parsed_model,
)

DEFAULT_ROLE = "default"
ROLE_REMEDY = "Spawn with a role at or below your model, or do the work yourself."


class RoleFile(NamedTuple):
    name: str | None
    model: str | None


class Spawn(NamedTuple):
    tool_input: JsonObject
    role: str
    role_applies: bool
    requested_model: str | None


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


def parsed_role_file(path: Path) -> RoleFile:
    table = read_toml(path)
    return RoleFile(text_or_none(table.get("name")), text_or_none(table.get("model")))


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
    user_folder = Path(os.environ.get("CODEX_HOME") or "~/.codex").expanduser()
    folders = config_folders(Path(cwd), Path(".codex"), user_folder)
    return [parsed_layer(folder) for folder in folders]


def role_model(role_name: str, layers: Iterable[CodexLayer]) -> str | None:
    for layer in layers:
        role_models = layer_role_models(layer)
        if role_name in role_models:
            return role_models[role_name]
    return None


def default_subagent_model(layers: Iterable[CodexLayer]) -> str | None:
    models = (layer.default_subagent_model for layer in layers)
    return next(filter(None, models), None)


def role_applies(tool_input: JsonObject, named_role: str) -> bool:
    is_v2 = "task_name" in tool_input
    if not is_v2:
        return tool_input.get("fork_context") is not True
    fork_turns = str(tool_input.get("fork_turns") or "").strip().lower()
    return bool(named_role) or fork_turns not in ("", "all")


def parsed_spawn(tool_input: JsonObject) -> Spawn:
    named_role = str(tool_input.get("agent_type") or "").strip()
    return Spawn(
        tool_input,
        named_role or DEFAULT_ROLE,
        role_applies(tool_input, named_role),
        text_or_none(tool_input.get("model")),
    )


def role_decision(
    spawn: Spawn, layers: list[CodexLayer], caller: Model | None
) -> PreToolUseDecision | None:
    if not spawn.role_applies:
        return None
    fixed_model = parsed_model(role_model(spawn.role, layers))
    reason = denial_reason(f"The {spawn.role} role", ROLE_REMEDY, fixed_model, caller)
    return denied(reason) if reason else None


def request_decision(
    spawn: Spawn, layers: list[CodexLayer], caller: Model | None
) -> PreToolUseDecision | None:
    requested_name = spawn.requested_model or default_subagent_model(layers)
    capped = capped_input(spawn.tool_input, parsed_model(requested_name), caller)
    return allowed_with(capped) if capped else None


def cap_decision(payload: JsonObject) -> PreToolUseDecision | None:
    caller = parsed_model(payload.get("model"))
    spawn = parsed_spawn(dict_or_empty(payload.get("tool_input")))
    layers = codex_layers(cwd_of(payload))
    return role_decision(spawn, layers, caller) or request_decision(
        spawn, layers, caller
    )


if __name__ == "__main__":
    run_pre_tool_use(cap_decision)
