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

from hook_io import PreToolUseDecision, cwd_of, denied, run_pre_tool_use
from json_values import JsonObject, JsonValue, dict_or_empty
from model_cap import outranks, project_folders, tier_rank
from plugin_paths import PLUGIN_ROOT
from transcript import recent_entries

INHERIT = "inherit"
TRUTHY_FLAGS = ("1", "true", "yes", "on")
FRONTMATTER = re.compile(r"---\s*\n([\s\S]*?)---\s*\n?")
CLAUDE_ALIASES = ("haiku", "sonnet", "opus", "fable")
SUBAGENT_MODEL_VARIABLE = "CLAUDE_CODE_SUBAGENT_MODEL"
PLUGIN_NAME = "misticos"
PLUGIN_AGENTS_DIR = PLUGIN_ROOT / "agents"


def with_model(tool_input: JsonObject, model: JsonValue) -> PreToolUseDecision:
    return {"updatedInput": {**tool_input, "model": model}}


def latest_model(transcript_path: str, include_sidechains: bool = False) -> JsonValue:
    for entry in recent_entries(transcript_path):
        if entry.get("isSidechain") and not include_sidechains:
            continue
        model = dict_or_empty(entry.get("message")).get("model")
        if tier_rank(model) is not None:
            return model
    return None


def subagent_transcript(transcript_path: str, agent_id: JsonValue) -> str:
    subagents_dir = os.path.join(transcript_path.removesuffix(".jsonl"), "subagents")
    pattern = os.path.join(subagents_dir, "**", f"agent-{agent_id}.jsonl")
    return next(iter(glob.glob(pattern, recursive=True)), "")


def caller_model(payload: JsonObject, main_model: JsonValue) -> JsonValue:
    agent_id = payload.get("agent_id")
    if not agent_id:
        return main_model
    main_transcript = payload["transcript_path"]
    if not isinstance(main_transcript, str):
        raise TypeError(f"transcript_path {main_transcript!r} is not a path")
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


def claude_alias(model: JsonValue) -> str | None:
    rank = tier_rank(model)
    return next((alias for alias in CLAUDE_ALIASES if tier_rank(alias) == rank), None)


def wanted_agent_model(definition: str | None, caller: JsonValue) -> JsonValue:
    model = definition or os.environ.get(SUBAGENT_MODEL_VARIABLE) or INHERIT
    return caller if model == INHERIT else model


def forced_decision(caller: JsonValue) -> PreToolUseDecision | None:
    forced_model = os.environ.get(SUBAGENT_MODEL_VARIABLE)
    if not outranks(forced_model, caller):
        return None
    return denied(
        f"CLAUDE_CODE_SUBAGENT_MODEL_FORCE runs every subagent on "
        f"{forced_model}, above your {caller}. Do the work yourself."
    )


def requested_model_decision(
    tool_input: JsonObject, caller: JsonValue
) -> PreToolUseDecision | None:
    if not outranks(tool_input.get("model"), caller):
        return None
    return with_model(tool_input, claude_alias(caller))


def definition_model_decision(
    tool_input: JsonObject, definition: str | None, caller: JsonValue
) -> PreToolUseDecision | None:
    wanted_model = wanted_agent_model(definition, caller)
    if claude_alias(wanted_model) is None:
        return None
    capped_model = caller if outranks(wanted_model, caller) else wanted_model
    return with_model(tool_input, claude_alias(capped_model))


def agent_decision(
    tool_input: JsonObject, cwd: str, caller: JsonValue
) -> PreToolUseDecision | None:
    force_flag = os.environ.get("CLAUDE_CODE_SUBAGENT_MODEL_FORCE", "")
    if force_flag.strip().lower() in TRUTHY_FLAGS:
        return forced_decision(caller)
    definition = definition_model(tool_input.get("subagent_type"), cwd)
    if tool_input.get("model") and claude_alias(definition) is None:
        return requested_model_decision(tool_input, caller)
    return definition_model_decision(tool_input, definition, caller)


def session_decision(
    tool_input: JsonObject, main_model: JsonValue, caller: JsonValue
) -> PreToolUseDecision | None:
    requested = tool_input.get("model") or main_model
    if not outranks(requested, caller):
        return None
    return with_model(tool_input, caller)


def cap_decision(payload: JsonObject) -> PreToolUseDecision | None:
    tool_input = dict_or_empty(payload.get("tool_input"))
    transcript_path = payload.get("transcript_path")
    main_model = latest_model(
        transcript_path if isinstance(transcript_path, str) else ""
    )
    caller = caller_model(payload, main_model)
    if payload.get("tool_name") in ("Agent", "Task"):
        return agent_decision(tool_input, cwd_of(payload), caller)
    return session_decision(tool_input, main_model, caller)


if __name__ == "__main__":
    run_pre_tool_use(cap_decision)
