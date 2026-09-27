#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///

import glob
import json
import os
import sys
from pathlib import Path

from model_tiers import outranks, tier_name, tier_rank

PLUGIN_CACHE = "~/.claude/plugins/cache"
INHERIT = "inherit"


def transcript_models(transcript_path, include_sidechains):
    try:
        with open(transcript_path, encoding="utf-8", errors="replace") as transcript:
            lines = transcript.readlines()
    except OSError:
        return
    for line in reversed(lines):
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
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
        with open(definition_path, encoding="utf-8") as definition:
            lines = definition.read().splitlines()
    except OSError:
        return {}
    if lines[:1] != ["---"]:
        return {}
    fields = {}
    for line in lines[1:]:
        if line == "---":
            return fields
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip().strip("\"'")
    return {}


def agent_dirs(cwd):
    project_dirs = [folder / ".claude" / "agents" for folder in (cwd, *cwd.parents)]
    return [*project_dirs, Path("~/.claude/agents").expanduser()]


def plugin_agent_dirs(plugin):
    pattern = os.path.join(os.path.expanduser(PLUGIN_CACHE), "*", plugin, "*", "agents")
    return map(Path, glob.glob(pattern))


def definitions_named(name, directories):
    for directory in directories:
        for path in sorted(directory.glob("**/*.md")):
            fields = frontmatter(path)
            if fields.get("name") == name:
                yield fields


def definition_model(subagent_type, cwd):
    if os.environ.get("CLAUDE_CODE_SUBAGENT_MODEL_FORCE") == "1":
        return None
    plugin, _, plugin_agent = str(subagent_type).rpartition(":")
    if plugin:
        definitions = definitions_named(plugin_agent, plugin_agent_dirs(plugin))
    else:
        definitions = definitions_named(subagent_type, agent_dirs(Path(cwd)))
    return next(definitions, {}).get("model")


def resolved_agent_model(tool_input, cwd, main_model):
    model = (
        tool_input.get("model")
        or definition_model(tool_input.get("subagent_type"), cwd)
        or os.environ.get("CLAUDE_CODE_SUBAGENT_MODEL")
        or INHERIT
    )
    return main_model if model == INHERIT else model


def capped_input(payload):
    tool_input = payload.get("tool_input") or {}
    main_model = latest_model(payload.get("transcript_path") or "")
    caller = caller_model(payload, main_model)
    if payload.get("tool_name") in ("Agent", "Task"):
        requested = resolved_agent_model(
            tool_input, payload.get("cwd") or os.getcwd(), main_model
        )
        capped = tier_name(caller)
    else:
        requested = tool_input.get("model") or main_model
        capped = caller
    if not outranks(requested, caller):
        return None
    return {**tool_input, "model": capped}


def main():
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        return
    updated_input = capped_input(payload)
    if not updated_input:
        return
    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "updatedInput": updated_input,
            }
        },
        sys.stdout,
    )


if __name__ == "__main__":
    main()
