#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# [tool.ty.environment]
# root = ["."]
# ///

import glob
import os
from collections.abc import Sequence
from pathlib import Path

from claude_agents import AgentFolder, agent_folders, definition_model
from hook_io import (
    PreToolUseDecision,
    cwd_of,
    denied,
    run_pre_tool_use,
    transcript_path_of,
)
from json_values import JsonObject, dict_or_empty, text_or_none
from model_cap import Model, claude_alias, outranks, parsed_model
from transcript import recent_entries

INHERIT = "inherit"
TRUTHY_FLAGS = ("1", "true", "yes", "on")
SUBAGENT_MODEL_VARIABLE = "CLAUDE_CODE_SUBAGENT_MODEL"


def with_model(tool_input: JsonObject, model: str | None) -> PreToolUseDecision:
    return {"updatedInput": {**tool_input, "model": model}}


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


def subagent_transcript(transcript_path: str, agent_id: str) -> str:
    subagents_dir = os.path.join(transcript_path.removesuffix(".jsonl"), "subagents")
    pattern = os.path.join(subagents_dir, "**", f"agent-{agent_id}.jsonl")
    return next(iter(glob.glob(pattern, recursive=True)), "")


def main_model(transcript_path: str | None) -> Model | None:
    return latest_model(transcript_path) if transcript_path else None


def caller_model(transcript_path: str | None, agent_id: str | None) -> Model | None:
    if agent_id is None:
        return main_model(transcript_path)
    if transcript_path is None:
        return None
    own_transcript = subagent_transcript(transcript_path, agent_id)
    return latest_model(own_transcript, include_sidechains=True)


def wanted_agent_model(definition: str | None, caller: Model | None) -> Model | None:
    model = definition or os.environ.get(SUBAGENT_MODEL_VARIABLE) or INHERIT
    return caller if model == INHERIT else parsed_model(model)


def forced_decision(caller: Model | None) -> PreToolUseDecision | None:
    forced_model = os.environ.get(SUBAGENT_MODEL_VARIABLE)
    if caller is None or not outranks(parsed_model(forced_model), caller):
        return None
    return denied(
        f"CLAUDE_CODE_SUBAGENT_MODEL_FORCE runs every subagent on "
        f"{forced_model}, above your {caller.name}. Do the work yourself."
    )


def requested_model_decision(
    tool_input: JsonObject, caller: Model | None
) -> PreToolUseDecision | None:
    if not outranks(parsed_model(tool_input.get("model")), caller):
        return None
    return with_model(tool_input, claude_alias(caller))


def definition_model_decision(
    tool_input: JsonObject, definition: str | None, caller: Model | None
) -> PreToolUseDecision | None:
    wanted_model = wanted_agent_model(definition, caller)
    if claude_alias(wanted_model) is None:
        return None
    capped_model = caller if outranks(wanted_model, caller) else wanted_model
    return with_model(tool_input, claude_alias(capped_model))


def agent_model_decision(
    tool_input: JsonObject, folders: Sequence[AgentFolder], caller: Model | None
) -> PreToolUseDecision | None:
    force_flag = os.environ.get("CLAUDE_CODE_SUBAGENT_MODEL_FORCE", "")
    if force_flag.strip().lower() in TRUTHY_FLAGS:
        return forced_decision(caller)
    subagent_type = text_or_none(tool_input.get("subagent_type"))
    definition = definition_model(subagent_type, folders)
    requested = text_or_none(tool_input.get("model"))
    if requested and claude_alias(parsed_model(definition)) is None:
        return requested_model_decision(tool_input, caller)
    return definition_model_decision(tool_input, definition, caller)


def without_effort(tool_input: JsonObject) -> JsonObject:
    return {key: value for key, value in tool_input.items() if key != "effort"}


def agent_decision(
    tool_input: JsonObject, folders: Sequence[AgentFolder], caller: Model | None
) -> PreToolUseDecision | None:
    agent_input = without_effort(tool_input)
    decision = agent_model_decision(agent_input, folders, caller)
    if decision is None and agent_input != tool_input:
        return {"updatedInput": agent_input}
    return decision


def session_decision(
    tool_input: JsonObject, main: Model | None, caller: Model | None
) -> PreToolUseDecision | None:
    requested = tool_input.get("model")
    requested_model = parsed_model(requested) if requested else main
    if caller is None or not outranks(requested_model, caller):
        return None
    return with_model(tool_input, caller.name)


def cap_decision(payload: JsonObject) -> PreToolUseDecision | None:
    tool_input = dict_or_empty(payload.get("tool_input"))
    transcript_path = transcript_path_of(payload)
    agent_id = text_or_none(payload.get("agent_id"))
    caller = caller_model(transcript_path, agent_id)
    if payload.get("tool_name") in ("Agent", "Task"):
        folders = agent_folders(Path(cwd_of(payload)))
        return agent_decision(tool_input, folders, caller)
    main = caller if agent_id is None else main_model(transcript_path)
    return session_decision(tool_input, main, caller)


if __name__ == "__main__":
    run_pre_tool_use(cap_decision)
