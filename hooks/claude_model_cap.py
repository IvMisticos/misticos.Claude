#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///

import glob
import json
import os
import re
import sys
from pathlib import Path

from model_tiers import outranks, tier_rank

INSTALLED_PLUGINS = "~/.claude/plugins/installed_plugins.json"
INHERIT = "inherit"
TRANSCRIPT_TAIL_BYTES = 1 << 20
TRUTHY_FLAGS = ("1", "true", "yes", "on")
FRONTMATTER = re.compile(r"---\s*\n([\s\S]*?)---\s*\n?")
CLAUDE_ALIASES = ("haiku", "sonnet", "opus", "fable")


def transcript_tail_lines(transcript_path):
    with open(transcript_path, "rb") as transcript:
        transcript.seek(0, os.SEEK_END)
        start = max(0, transcript.tell() - TRANSCRIPT_TAIL_BYTES)
        transcript.seek(start)
        lines = transcript.read().split(b"\n")
    return lines if start == 0 else lines[1:]


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


def project_folders(cwd):
    for folder in (cwd, *cwd.parents):
        yield folder
        if (folder / ".git").exists():
            return


def agent_dirs(cwd):
    project_dirs = [folder / ".claude" / "agents" for folder in project_folders(cwd)]
    return [*project_dirs, Path("~/.claude/agents").expanduser()]


def installed_plugins():
    try:
        with open(os.path.expanduser(INSTALLED_PLUGINS), encoding="utf-8") as registry:
            registry_data = json.load(registry)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    plugins = registry_data.get("plugins") if isinstance(registry_data, dict) else None
    return plugins if isinstance(plugins, dict) else {}


def plugin_agent_dirs(plugin):
    for key, installs in installed_plugins().items():
        if key.split("@", 1)[0] != plugin or not isinstance(installs, list):
            continue
        for install in installs:
            if isinstance(install, dict) and install.get("installPath"):
                yield Path(install["installPath"]) / "agents"


def loose_name(name):
    return re.sub(r"[\s_-]", "", str(name).lower())


def definitions_in(directories):
    for directory in directories:
        for path in sorted(directory.glob("**/*.md")):
            yield frontmatter(path)


def definition_named(name, directories):
    definitions = [
        fields for fields in definitions_in(directories) if fields.get("name")
    ]
    exact = [fields for fields in definitions if fields["name"] == name]
    if exact:
        return exact[0]
    loose = [
        fields
        for fields in definitions
        if loose_name(fields["name"]) == loose_name(name)
    ]
    return loose[0] if len(loose) == 1 else {}


def definition_model(subagent_type, cwd):
    if not subagent_type:
        return None
    plugin, _, plugin_agent = str(subagent_type).rpartition(":")
    if plugin:
        return definition_named(plugin_agent, plugin_agent_dirs(plugin)).get("model")
    return definition_named(subagent_type, agent_dirs(Path(cwd))).get("model")


def claude_alias(model):
    rank = tier_rank(model)
    return next((alias for alias in CLAUDE_ALIASES if tier_rank(alias) == rank), None)


def wanted_agent_model(definition, caller):
    if definition == INHERIT:
        return caller
    return definition or os.environ.get("CLAUDE_CODE_SUBAGENT_MODEL") or caller


def is_forced():
    flag = os.environ.get("CLAUDE_CODE_SUBAGENT_MODEL_FORCE", "")
    return flag.strip().lower() in TRUTHY_FLAGS


def forced_model_denial(forced_model, caller):
    return {
        "permissionDecision": "deny",
        "permissionDecisionReason": (
            f"CLAUDE_CODE_SUBAGENT_MODEL_FORCE runs every subagent on "
            f"{forced_model}, above your {caller}. Do the work yourself."
        ),
    }


def agent_decision(tool_input, cwd, caller):
    if is_forced():
        forced_model = os.environ.get("CLAUDE_CODE_SUBAGENT_MODEL")
        if outranks(forced_model, caller):
            return forced_model_denial(forced_model, caller)
        return None
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


def main():
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        return
    decision = cap_decision(payload)
    if not decision:
        return
    json.dump(
        {"hookSpecificOutput": {"hookEventName": "PreToolUse", **decision}},
        sys.stdout,
    )


if __name__ == "__main__":
    main()
