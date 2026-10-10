#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///

import glob
import os
import re
from pathlib import Path

from hook_io import run_pre_tool_use
from model_cap import outranks, project_folders, tier_rank
from transcript import dict_or_empty, recent_entries

INHERIT = "inherit"
TRUTHY_FLAGS = ("1", "true", "yes", "on")
FRONTMATTER = re.compile(r"---\s*\n([\s\S]*?)---\s*\n?")
CLAUDE_ALIASES = ("haiku", "sonnet", "opus", "fable")
SUBAGENT_MODEL_VARIABLE = "CLAUDE_CODE_SUBAGENT_MODEL"
PLUGIN_NAME = "misticos"
PLUGIN_AGENTS_DIR = Path(__file__).resolve().parent.parent / "agents"


def with_model(tool_input, model):
    return {"updatedInput": {**tool_input, "model": model}}


def latest_model(transcript_path, include_sidechains=False):
    for entry in recent_entries(transcript_path):
        if entry.get("isSidechain") and not include_sidechains:
            continue
        model = dict_or_empty(entry.get("message")).get("model")
        if tier_rank(model) is not None:
            return model
    return None


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


def definition_text(definition_path):
    try:
        with open(definition_path, encoding="utf-8", errors="replace") as definition:
            return definition.read().lstrip("\ufeff").replace("\r\n", "\n")
    except OSError:
        return ""


def frontmatter_fields(text):
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


def agent_definitions(cwd):
    sources = [(directory, "**/*.md", "") for directory in agent_dirs(cwd)]
    sources.append((PLUGIN_AGENTS_DIR, "*.md", f"{PLUGIN_NAME}:"))
    for directory, pattern, name_prefix in sources:
        for path in sorted(directory.glob(pattern)):
            fields = frontmatter_fields(definition_text(path))
            yield name_prefix + fields.get("name", ""), fields


def definition_model(subagent_type, cwd):
    if not subagent_type:
        return None
    definitions = agent_definitions(Path(cwd))
    named = (fields for name, fields in definitions if name == subagent_type)
    return next(named, {}).get("model")


def claude_alias(model):
    rank = tier_rank(model)
    return next((alias for alias in CLAUDE_ALIASES if tier_rank(alias) == rank), None)


def wanted_agent_model(definition, caller):
    model = definition or os.environ.get(SUBAGENT_MODEL_VARIABLE) or INHERIT
    return caller if model == INHERIT else model


def forced_decision(caller):
    forced_model = os.environ.get(SUBAGENT_MODEL_VARIABLE)
    if not outranks(forced_model, caller):
        return None
    return {
        "permissionDecision": "deny",
        "permissionDecisionReason": (
            f"CLAUDE_CODE_SUBAGENT_MODEL_FORCE runs every subagent on "
            f"{forced_model}, above your {caller}. Do the work yourself."
        ),
    }


def requested_model_decision(tool_input, caller):
    if not outranks(tool_input.get("model"), caller):
        return None
    return with_model(tool_input, claude_alias(caller))


def definition_model_decision(tool_input, definition, caller):
    wanted_model = wanted_agent_model(definition, caller)
    if claude_alias(wanted_model) is None:
        return None
    capped_model = caller if outranks(wanted_model, caller) else wanted_model
    return with_model(tool_input, claude_alias(capped_model))


def agent_decision(tool_input, cwd, caller):
    force_flag = os.environ.get("CLAUDE_CODE_SUBAGENT_MODEL_FORCE", "")
    if force_flag.strip().lower() in TRUTHY_FLAGS:
        return forced_decision(caller)
    definition = definition_model(tool_input.get("subagent_type"), cwd)
    if tool_input.get("model") and claude_alias(definition) is None:
        return requested_model_decision(tool_input, caller)
    return definition_model_decision(tool_input, definition, caller)


def session_decision(tool_input, main_model, caller):
    requested = tool_input.get("model") or main_model
    if not outranks(requested, caller):
        return None
    return with_model(tool_input, caller)


def cap_decision(payload):
    tool_input = payload.get("tool_input") or {}
    main_model = latest_model(payload.get("transcript_path") or "")
    caller = caller_model(payload, main_model)
    if payload.get("tool_name") in ("Agent", "Task"):
        cwd = payload.get("cwd") or os.getcwd()
        return agent_decision(tool_input, cwd, caller)
    return session_decision(tool_input, main_model, caller)


if __name__ == "__main__":
    run_pre_tool_use(cap_decision)
