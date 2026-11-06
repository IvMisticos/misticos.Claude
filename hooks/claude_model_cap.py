#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# [tool.ty.environment]
# root = ["."]
# ///

import glob
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import NamedTuple

from claude_agents import AgentFolder, agent_folders, definition_model
from hook_io import (
    PreToolUseDecision,
    cwd_of,
    denied,
    run_pre_tool_use,
    transcript_path_of,
)
from json_values import JsonObject, dict_or_empty, text_or_none
from model_cap import (
    Model,
    capped_input,
    claude_alias,
    denial_reason,
    outranks,
    parsed_model,
)
from transcript import recent_entries

INHERIT = "inherit"
TRUTHY_FLAGS = ("1", "true", "yes", "on")
AGENT_TOOLS = ("Agent", "Task")
SUBAGENT_MODEL_VARIABLE = "CLAUDE_CODE_SUBAGENT_MODEL"
FORCE_VARIABLE = "CLAUDE_CODE_SUBAGENT_MODEL_FORCE"
FORCED_SUBAGENTS = f"With {FORCE_VARIABLE} set, every subagent"


class SubagentConfig(NamedTuple):
    agent_folders: Sequence[AgentFolder]
    default_model: str | None
    model_forced: bool


class AgentCall(NamedTuple):
    tool_input: JsonObject
    subagent_type: str | None
    requested_model: str | None


def subagent_config(
    cwd: Path, home: Path, environment: Mapping[str, str]
) -> SubagentConfig:
    force_flag = environment.get(FORCE_VARIABLE, "")
    return SubagentConfig(
        agent_folders(cwd, home),
        environment.get(SUBAGENT_MODEL_VARIABLE) or None,
        force_flag.strip().lower() in TRUTHY_FLAGS,
    )


def without_effort(tool_input: JsonObject) -> JsonObject:
    return {key: value for key, value in tool_input.items() if key != "effort"}


def agent_call(tool_input: JsonObject) -> AgentCall:
    return AgentCall(
        without_effort(tool_input),
        text_or_none(tool_input.get("subagent_type")),
        text_or_none(tool_input.get("model")),
    )


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


def subagent_transcript(transcript_path: str, agent_id: str) -> str:
    subagents_dir = os.path.join(transcript_path.removesuffix(".jsonl"), "subagents")
    pattern = os.path.join(subagents_dir, "**", f"agent-{agent_id}.jsonl")
    return next(iter(glob.glob(pattern, recursive=True)), "")


def main_model(transcript_path: str | None) -> Model | None:
    return latest_model(transcript_path) if transcript_path else None


def subagent_model(transcript_path: str | None, agent_id: str) -> Model | None:
    if transcript_path is None:
        return None
    own_transcript = subagent_transcript(transcript_path, agent_id)
    return latest_model(own_transcript, include_sidechains=True)


def caller_model(transcript_path: str | None, agent_id: str | None) -> Model | None:
    if agent_id is None:
        return main_model(transcript_path)
    return subagent_model(transcript_path, agent_id)


def setting_model(setting: str, caller: Model | None) -> Model | None:
    return caller if setting == INHERIT else parsed_model(setting)


def requested_model_decision(
    call: AgentCall, caller: Model | None
) -> PreToolUseDecision | None:
    requested = parsed_model(call.requested_model)
    capped = capped_input(call.tool_input, requested, caller, claude_alias)
    return with_input(capped) if capped else None


def wanted_model_decision(
    tool_input: JsonObject, wanted: Model | None, caller: Model | None
) -> PreToolUseDecision | None:
    if claude_alias(wanted) is None:
        return None
    allowed = caller if outranks(wanted, caller) else wanted
    return with_model(tool_input, claude_alias(allowed))


def agent_model_decision(
    call: AgentCall, caller: Model | None, config: SubagentConfig
) -> PreToolUseDecision | None:
    if config.model_forced:
        forced = parsed_model(config.default_model)
        reason = denial_reason(FORCED_SUBAGENTS, forced, caller)
        return denied(reason) if reason else None
    definition = (
        definition_model(call.subagent_type, config.agent_folders)
        if call.subagent_type
        else None
    )
    pinned = parsed_model(definition)
    if call.requested_model and claude_alias(pinned) is None:
        return requested_model_decision(call, caller)
    setting = definition or config.default_model or INHERIT
    wanted = pinned or setting_model(setting, caller)
    return wanted_model_decision(call.tool_input, wanted, caller)


def agent_decision(
    tool_input: JsonObject, caller: Model | None, config: SubagentConfig
) -> PreToolUseDecision | None:
    call = agent_call(tool_input)
    decision = agent_model_decision(call, caller, config)
    if decision is None and call.tool_input != tool_input:
        return with_input(call.tool_input)
    return decision


def session_decision(
    tool_input: JsonObject, main: Model | None, caller: Model | None
) -> PreToolUseDecision | None:
    requested = tool_input.get("model")
    requested_model = parsed_model(requested) if requested else main
    capped = capped_input(tool_input, requested_model, caller)
    return with_input(capped) if capped else None


def cap_decision(payload: JsonObject) -> PreToolUseDecision | None:
    tool_input = dict_or_empty(payload.get("tool_input"))
    transcript_path = transcript_path_of(payload)
    agent_id = text_or_none(payload.get("agent_id"))
    if payload.get("tool_name") in AGENT_TOOLS:
        config = subagent_config(Path(cwd_of(payload)), Path.home(), os.environ)
        caller = caller_model(transcript_path, agent_id)
        return agent_decision(tool_input, caller, config)
    main = main_model(transcript_path)
    caller = main if agent_id is None else subagent_model(transcript_path, agent_id)
    return session_decision(tool_input, main, caller)


if __name__ == "__main__":
    run_pre_tool_use(cap_decision)
