#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///

import json
import re
import shlex
import sys

OVERRIDE_MARK = "# misticos.Claude.ignore"
PULL_REQUEST_WRITE_METHODS = {"POST", "PUT"}


def command_words(command):
    try:
        return shlex.split(command, comments=True)
    except ValueError:
        return command.split()


def is_pull_request_write_through_gh(words):
    if words[:2] == ["gh", "pr"] and words[2:3] and words[2] in ("merge", "create"):
        return True
    if words[:2] != ["gh", "api"]:
        return False
    method = "GET"
    for index, word in enumerate(words):
        if word in ("-X", "--method") and index + 1 < len(words):
            method = words[index + 1].upper()
        if word in ("-f", "-F", "--field", "--raw-field", "--input"):
            method = "POST"
    touches_pull_requests = any("/pulls" in word for word in words)
    return touches_pull_requests and method in PULL_REQUEST_WRITE_METHODS


def sets_git_identity(words):
    if words[:1] != ["git"]:
        return False
    identity_keys = ("user.name", "user.email")
    if "config" in words:
        return any(word in identity_keys for word in words)
    for index, word in enumerate(words):
        value = word[2:] if word.startswith("-c") and len(word) > 2 else None
        if word == "-c" and index + 1 < len(words):
            value = words[index + 1]
        if value and value.split("=", 1)[0] in identity_keys:
            return True
    return False


def denial_reason(command):
    if OVERRIDE_MARK in command:
        return None
    for segment in re.split(r"&&|\|\||;|\|", command):
        words = command_words(segment.strip())
        if not words:
            continue
        if is_pull_request_write_through_gh(words):
            return (
                "Merge and create pull requests with the GitHub MCP tools, not gh. "
                f"If the MCP cannot do it, append {OVERRIDE_MARK} to the command."
            )
        if sets_git_identity(words):
            return (
                "Keep the git identity the harness set. "
                f"If a change is genuinely needed, append {OVERRIDE_MARK} to the command."
            )
    return None


def main():
    payload = json.loads(sys.stdin.read() or "{}")
    command = str((payload.get("tool_input") or {}).get("command") or "")
    reason = denial_reason(command)
    if reason is None:
        return
    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        },
        sys.stdout,
    )


if __name__ == "__main__":
    main()
