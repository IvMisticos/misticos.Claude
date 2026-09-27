#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///

import glob
import json
import os
import re
from pathlib import Path

from model_cap import outranks, project_folders, run_pre_tool_use, tier_rank
from reminder import transcript_tail_lines

INHERIT = "inherit"
TRUTHY_FLAGS = ("1", "true", "yes", "on")
FRONTMATTER = re.compile(r"---\s*\n([\s\S]*?)---\s*\n?")
CLAUDE_ALIASES = ("haiku", "sonnet", "opus", "fable")


def transcript_models(transcript_path, include_sidechains):
    try:
        lines = transcript_tail_lines(transcript_path)
    except OSError:
        return
    for line in reversed(lines):
        try:
            entry = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        if not isinstance(entry, dict) or entry.get("type") != "assistant":
            continue
        if entry.get("isSidechain") and not include_sidechains:
            continue
        message = entry.get("message")
        model = message.get("model") if isinstance(message, dict) else None
        if tier_rank(model) is not None:
            yield model


def latest_model(transcript_path, include_sidechains=False):
    return next(transcript_models(transcript_path, include_sidechains), None)


def subagent_transcript(transcript_path, agent_id):
    subagents_dir = os.path.join(transcript_path.removesuffix(".jsonl"), "subagents")
    pattern = os.path.join(subagents_dir, "**", f"agent-{agent_id}.jsonl")
    return next(iter(glob.glob(pattern, recursive=True)), "")


def caller_model(payload, main_model):
    agent_id = payload.get("agent_id")
    if not agent_id:
        return main_model
    transcript_path = subagent_transcript(payload["transcript_path"], agent_id)
    return latest_model(transcript_path, include_sidechains=True)


def frontmatter(definition_path):
    try:
        with open(definition_path, encoding="utf-8", errors="replace") as definition:
            text = definition.read().lstrip("\ufeff").replace("\r\n", "\n")
    except OSError:
        return {}
    block = FRONTMATTER.match(text)
    if not block:
        return {}
    top_level_lines = (
        line for line in block[1].splitlines() if line and not line[0].isspace()
    )
    fields = {}
    for line in top_level_lines:
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip().strip("\"'")
    return fields


def agent_dirs(cwd):
    project_dirs = [folder / ".claude" / "agents" for folder in project_folders(cwd)]
    return [*project_dirs, Path("~/.claude/agents").expanduser()]


def definition_model(subagent_type, cwd):
    if not subagent_type:
        return None
    definitions = (
        frontmatter(path)
        for directory in agent_dirs(Path(cwd))
        for path in sorted(directory.glob("**/*.md"))
    )
    named = (fields for fields in definitions if fields.get("name") == subagent_type)
    return next(named, {}).get("model")


def claude_alias(model):
    rank = tier_rank(model)
    return next((alias for alias in CLAUDE_ALIASES if tier_rank(alias) == rank), None)


def wanted_agent_model(definition, caller):
    model = definition or os.environ.get("CLAUDE_CODE_SUBAGENT_MODEL") or INHERIT
    return caller if model == INHERIT else model


def forced_decision(caller):
    forced_model = os.environ.get("CLAUDE_CODE_SUBAGENT_MODEL")
    if not outranks(forced_model, caller):
        return None
    return {
        "permissionDecision": "deny",
        "permissionDecisionReason": (
            f"CLAUDE_CODE_SUBAGENT_MODEL_FORCE runs every subagent on "
            f"{forced_model}, above your {caller}. Do the work yourself."
        ),
    }


def agent_decision(tool_input, cwd, caller):
    force_flag = os.environ.get("CLAUDE_CODE_SUBAGENT_MODEL_FORCE", "")
    if force_flag.strip().lower() in TRUTHY_FLAGS:
        return forced_decision(caller)
    requested_model = tool_input.get("model")
    if requested_model:
        if not outranks(requested_model, caller):
            return None
        return {"updatedInput": {**tool_input, "model": claude_alias(caller)}}
    definition = definition_model(tool_input.get("subagent_type"), cwd)
    wanted_model = wanted_agent_model(definition, caller)
    if not claude_alias(wanted_model):
        return None
    pinned_model = caller if outranks(wanted_model, caller) else wanted_model
    return {"updatedInput": {**tool_input, "model": claude_alias(pinned_model)}}


def session_decision(tool_input, main_model, caller):
    requested = tool_input.get("model") or main_model
    if not outranks(requested, caller):
        return None
    return {"updatedInput": {**tool_input, "model": caller}}


def cap_decision(payload):
    tool_input = payload.get("tool_input") or {}
    main_model = latest_model(payload.get("transcript_path") or "")
    caller = caller_model(payload, main_model)
    if not claude_alias(caller):
        return None
    if payload.get("tool_name") in ("Agent", "Task"):
        cwd = payload.get("cwd") or os.getcwd()
        return agent_decision(tool_input, cwd, caller)
    return session_decision(tool_input, main_model, caller)


if __name__ == "__main__":
    run_pre_tool_use(cap_decision)
