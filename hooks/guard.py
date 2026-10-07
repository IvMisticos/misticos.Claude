#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///

import json
import os
import re
import shlex
import sys

OVERRIDE_MARK = "# misticos.Claude.ignore"
PULL_REQUEST_WRITE_METHODS = {"POST", "PUT"}
SEGMENT_SEPARATORS = re.compile(r"&&|\|\||\$?\(|[;&|\n(){}]")
SHELL_RUNNERS = {"bash", "sh", "zsh", "eval"}
GUARDED_PROGRAMS = {"gh", *SHELL_RUNNERS}


def command_words(command):
    try:
        return shlex.split(command, comments=True)
    except ValueError:
        return command.split()


def from_guarded_program(words):
    for index, word in enumerate(words):
        if os.path.basename(word) in GUARDED_PROGRAMS:
            return [os.path.basename(word), *words[index + 1 :]]
    return []


def gh_api_method(words):
    method = None
    fields_given = False
    for index, word in enumerate(words):
        if word in ("-X", "--method") and index + 1 < len(words):
            method = words[index + 1].upper()
        elif word.startswith("--method="):
            method = word.split("=", 1)[1].upper()
        elif word.startswith("-X") and len(word) > 2:
            method = word[2:].upper()
        elif word in (
            "-f",
            "-F",
            "--field",
            "--raw-field",
            "--input",
        ) or word.startswith(("--field=", "--raw-field=", "--input=")):
            fields_given = True
    if method is None:
        return "POST" if fields_given else "GET"
    return method


def is_pull_request_write_through_gh(words):
    if words[:2] == ["gh", "pr"] and words[2:3] and words[2] in ("merge", "create"):
        return True
    if words[:2] != ["gh", "api"]:
        return False
    touches_pull_requests = any("/pulls" in word for word in words)
    return touches_pull_requests and gh_api_method(words) in PULL_REQUEST_WRITE_METHODS


def segment_denial(segment):
    raw_words = command_words(segment.strip())
    words = from_guarded_program(raw_words)
    if not words:
        return None
    if words[0] in SHELL_RUNNERS:
        return next(
            (reason for reason in map(denial_reason, words[1:]) if reason), None
        )
    if is_pull_request_write_through_gh(words):
        return (
            "Merge and create pull requests with the GitHub MCP tools, not gh. "
            f"If the MCP cannot do it, end the command with {OVERRIDE_MARK}."
        )
    return None


def denial_reason(command):
    if command.rstrip().endswith(OVERRIDE_MARK):
        return None
    for segment in SEGMENT_SEPARATORS.split(command):
        reason = segment_denial(segment)
        if reason:
            return reason
    return None


def deny(reason):
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


def main():
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        return
    command = str((payload.get("tool_input") or {}).get("command") or "")
    reason = denial_reason(command)
    if reason:
        deny(reason)


if __name__ == "__main__":
    main()
