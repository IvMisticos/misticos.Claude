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
WRAPPER_WORDS = {"(", "{", "!", "if", "then", "else", "do", "command", "env", "exec", "sudo"}
SHELL_RUNNERS = {"bash", "sh", "zsh", "eval"}
IDENTITY_KEYS = ("user.name", "user.email")
IDENTITY_VARIABLES = ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL")


def command_words(command):
    try:
        return shlex.split(command, comments=True)
    except ValueError:
        return command.split()


def sets_identity_variable(word):
    return "=" in word and word.split("=", 1)[0] in IDENTITY_VARIABLES


def without_wrappers(words):
    while words and (words[0] in WRAPPER_WORDS or re.fullmatch(r"[A-Za-z_]\w*=.*", words[0])):
        words = words[1:]
    if words:
        words = [os.path.basename(words[0]), *words[1:]]
    return words


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
        elif word in ("-f", "-F", "--field", "--raw-field", "--input") or word.startswith(("--field=", "--raw-field=", "--input=")):
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


def git_config_writes_identity(words):
    if "config" not in words:
        return False
    after_config = words[words.index("config") + 1 :]
    reads = {"--get", "--get-all", "--get-regexp", "--list", "-l", "--show-origin"}
    if any(word in reads for word in after_config):
        return False
    return any(word in IDENTITY_KEYS for word in after_config)


def git_overrides_identity(words):
    for index, word in enumerate(words):
        value = word[2:] if word.startswith("-c") and len(word) > 2 else None
        if word == "-c" and index + 1 < len(words):
            value = words[index + 1]
        if value and value.split("=", 1)[0] in IDENTITY_KEYS:
            return True
        if word == "--author" or word.startswith("--author="):
            return True
    return False


def sets_git_identity(raw_words, words):
    if any(sets_identity_variable(word) for word in raw_words):
        return True
    if words[:1] != ["git"]:
        return False
    return git_config_writes_identity(words) or git_overrides_identity(words)


def segment_denial(segment):
    raw_words = command_words(segment.strip())
    words = without_wrappers(raw_words)
    if not words:
        return None
    if words[0] in SHELL_RUNNERS:
        return next((reason for reason in map(denial_reason, words[1:]) if reason), None)
    if is_pull_request_write_through_gh(words):
        return (
            "Merge and create pull requests with the GitHub MCP tools, not gh. "
            f"If the MCP cannot do it, end the command with {OVERRIDE_MARK}."
        )
    if sets_git_identity(raw_words, words):
        return (
            "Keep the git identity the harness set. "
            f"If a change is genuinely needed, end the command with {OVERRIDE_MARK}."
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
