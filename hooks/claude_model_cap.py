#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///

import glob
import json
import os
import sys

from model_tiers import outranks, tier_name, tier_rank

AGENT_DEFINITION_DIRS = ("{cwd}/.claude/agents", "~/.claude/agents")
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


def frontmatter_model(definition_path):
    try:
        with open(definition_path, encoding="utf-8") as definition:
            lines = definition.read().splitlines()
    except OSError:
        return None
    if lines[:1] != ["---"]:
        return None
    for line in lines[1:]:
        if line == "---":
            return None
        key, _, value = line.partition(":")
        if key.strip() == "model":
            return value.strip().strip("\"'")
    return None


def definition_model(subagent_type, cwd):
    if os.environ.get("CLAUDE_CODE_SUBAGENT_MODEL_FORCE") == "1":
        return None
    for directory in AGENT_DEFINITION_DIRS:
        path = os.path.expanduser(directory.format(cwd=cwd))
        model = frontmatter_model(os.path.join(path, f"{subagent_type}.md"))
        if model:
            return model
    return None


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
        requested = resolved_agent_model(tool_input, payload.get("cwd"), main_model)
        capped = tier_name(caller)
    else:
        requested = tool_input.get("model")
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
