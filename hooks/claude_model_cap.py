#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# [tool.ty.environment]
# root = ["."]
# ///

import glob
import os
import re
from collections.abc import Iterator
from pathlib import Path

from hook_io import (
    PreToolUseDecision,
    cwd_of,
    denied,
    run_pre_tool_use,
    transcript_path_of,
)
from json_values import JsonObject, JsonValue, dict_or_empty
from model_cap import (
    Model,
    capped_input,
    claude_alias,
    outranks,
    parsed_model,
    project_folders,
)
from plugin_paths import PLUGIN_ROOT
from transcript import recent_entries

INHERIT = "inherit"
TRUTHY_FLAGS = ("1", "true", "yes", "on")
FRONTMATTER = re.compile(r"---\s*\n([\s\S]*?)---\s*\n?")
SUBAGENT_MODEL_VARIABLE = "CLAUDE_CODE_SUBAGENT_MODEL"
PLUGIN_NAME = "misticos"
PLUGIN_AGENTS_DIR = PLUGIN_ROOT / "agents"


def with_input(tool_input: JsonObject) -> PreToolUseDecision:
    return {"updatedInput": tool_input}


def with_model(tool_input: JsonObject, model: str | None) -> PreToolUseDecision:
    return with_input({**tool_input, "model": model})


def latest_model(
    transcript_path: str, include_sidechains: bool = False
) -> Model | None:
    for entry in recent_entries(transcript_path):
        if entry.get("isSidechain") and not include_sidechains:
            continue
        model = parsed_model(dict_or_empty(entry.get("message")).get("model"))
        if model:
            return model
    return None


def subagent_transcript(transcript_path: str, agent_id: JsonValue) -> str:
    subagents_dir = os.path.join(transcript_path.removesuffix(".jsonl"), "subagents")
    pattern = os.path.join(subagents_dir, "**", f"agent-{agent_id}.jsonl")
    return next(iter(glob.glob(pattern, recursive=True)), "")


def caller_model(payload: JsonObject, main_model: Model | None) -> Model | None:
    agent_id = payload.get("agent_id")
    if not agent_id:
        return main_model
    main_transcript = transcript_path_of(payload)
    if main_transcript is None:
        return None
    transcript_path = subagent_transcript(main_transcript, agent_id)
    return latest_model(transcript_path, include_sidechains=True)


def definition_text(definition_path: Path) -> str:
    try:
        with open(definition_path, encoding="utf-8", errors="replace") as definition:
            return definition.read().lstrip("\ufeff").replace("\r\n", "\n")
    except OSError:
        return ""


def frontmatter_fields(text: str) -> dict[str, str]:
    block = FRONTMATTER.match(text)
    if not block:
        return {}
    top_level_lines = (
        line for line in block[1].splitlines() if line and not line[0].isspace()
    )
    fields: dict[str, str] = {}
    for line in top_level_lines:
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip().strip("\"'")
    return fields


def agent_dirs(cwd: Path) -> list[Path]:
    project_dirs = [folder / ".claude" / "agents" for folder in project_folders(cwd)]
    return [*project_dirs, Path("~/.claude/agents").expanduser()]


def agent_definitions(cwd: Path) -> Iterator[tuple[str, dict[str, str]]]:
    sources = [(directory, "**/*.md", "") for directory in agent_dirs(cwd)]
    sources.append((PLUGIN_AGENTS_DIR, "*.md", f"{PLUGIN_NAME}:"))
    for directory, pattern, name_prefix in sources:
        for path in sorted(directory.glob(pattern)):
            fields = frontmatter_fields(definition_text(path))
            yield name_prefix + fields.get("name", ""), fields


def definition_model(subagent_type: JsonValue, cwd: str) -> str | None:
    if not subagent_type:
        return None
    definitions = agent_definitions(Path(cwd))
    named = (fields for name, fields in definitions if name == subagent_type)
    return next(named, {}).get("model")


def wanted_agent_model(definition: str | None, caller: Model | None) -> Model | None:
    model = definition or os.environ.get(SUBAGENT_MODEL_VARIABLE) or INHERIT
    return caller if model == INHERIT else parsed_model(model)


def forced_decision(caller: Model | None) -> PreToolUseDecision | None:
    forced_model = parsed_model(os.environ.get(SUBAGENT_MODEL_VARIABLE))
    if forced_model is None or caller is None or not outranks(forced_model, caller):
        return None
    return denied(
        f"CLAUDE_CODE_SUBAGENT_MODEL_FORCE runs every subagent on "
        f"{forced_model.name}, above your {caller.name}. Do the work yourself."
    )


def requested_model_decision(
    tool_input: JsonObject, caller: Model | None
) -> PreToolUseDecision | None:
    requested = parsed_model(tool_input.get("model"))
    capped = capped_input(tool_input, requested, caller, claude_alias)
    return with_input(capped) if capped else None


def definition_model_decision(
    tool_input: JsonObject, definition: str | None, caller: Model | None
) -> PreToolUseDecision | None:
    wanted_model = wanted_agent_model(definition, caller)
    if claude_alias(wanted_model) is None:
        return None
    capped_model = caller if outranks(wanted_model, caller) else wanted_model
    return with_model(tool_input, claude_alias(capped_model))


def agent_model_decision(
    tool_input: JsonObject, cwd: str, caller: Model | None
) -> PreToolUseDecision | None:
    force_flag = os.environ.get("CLAUDE_CODE_SUBAGENT_MODEL_FORCE", "")
    if force_flag.strip().lower() in TRUTHY_FLAGS:
        return forced_decision(caller)
    definition = definition_model(tool_input.get("subagent_type"), cwd)
    if tool_input.get("model") and claude_alias(parsed_model(definition)) is None:
        return requested_model_decision(tool_input, caller)
    return definition_model_decision(tool_input, definition, caller)


def without_effort(tool_input: JsonObject) -> JsonObject:
    return {key: value for key, value in tool_input.items() if key != "effort"}


def agent_decision(
    tool_input: JsonObject, cwd: str, caller: Model | None
) -> PreToolUseDecision | None:
    agent_input = without_effort(tool_input)
    decision = agent_model_decision(agent_input, cwd, caller)
    if decision is None and agent_input != tool_input:
        return with_input(agent_input)
    return decision


def session_decision(
    tool_input: JsonObject, main_model: Model | None, caller: Model | None
) -> PreToolUseDecision | None:
    requested = tool_input.get("model")
    requested_model = parsed_model(requested) if requested else main_model
    capped = capped_input(tool_input, requested_model, caller)
    return with_input(capped) if capped else None


def cap_decision(payload: JsonObject) -> PreToolUseDecision | None:
    tool_input = dict_or_empty(payload.get("tool_input"))
    transcript_path = transcript_path_of(payload)
    main_model = latest_model(transcript_path) if transcript_path else None
    caller = caller_model(payload, main_model)
    if payload.get("tool_name") in ("Agent", "Task"):
        return agent_decision(tool_input, cwd_of(payload), caller)
    return session_decision(tool_input, main_model, caller)


if __name__ == "__main__":
    run_pre_tool_use(cap_decision)
