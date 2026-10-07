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
GUARDED_PROGRAMS = {"gh", "git", *SHELL_RUNNERS}
IDENTITY_KEYS = ("user.name", "user.email")
COMMIT_WRITING_SUBCOMMANDS = {
    "commit",
    "am",
    "cherry-pick",
    "rebase",
    "revert",
    "merge",
}
IDENTITY_VARIABLES = (
    "GIT_AUTHOR_NAME",
    "GIT_AUTHOR_EMAIL",
    "GIT_COMMITTER_NAME",
    "GIT_COMMITTER_EMAIL",
    "GIT_CONFIG_PARAMETERS",
)
ASSIGNMENT = re.compile(r"(?P<name>[A-Za-z_]\w*)\+?=(?P<value>.*)", re.DOTALL)
ASSIGNING_COMMANDS = {"export", "env", "declare", "typeset", "readonly", "local"}
CONFIG_READ_OPTIONS = {
    "--get",
    "--get-all",
    "--get-regexp",
    "--get-urlmatch",
    "--list",
    "-l",
}
SECTION_COMMANDS = {
    "--remove-section",
    "--rename-section",
    "remove-section",
    "rename-section",
}
IDENTITY_DENIAL = (
    "Keep the git identity the harness set. Read it with git config --get. "
    f"If a change is genuinely needed, end the command with {OVERRIDE_MARK}."
)


def command_words(command):
    try:
        return shlex.split(command, comments=True)
    except ValueError:
        return command.split()


def leading_assignments(words):
    for word in words:
        if word in ASSIGNING_COMMANDS or word.startswith("-"):
            continue
        assignment = ASSIGNMENT.fullmatch(word)
        if not assignment:
            return
        yield assignment


def assignments_before_program(words):
    program_index = guarded_program_index(words)
    if program_index is None:
        return leading_assignments(words)
    return filter(None, map(ASSIGNMENT.fullmatch, words[:program_index]))


def sets_identity_variable(assignment):
    if assignment["name"].startswith("GIT_CONFIG_KEY_"):
        return assignment["value"].lower() in IDENTITY_KEYS
    return assignment["name"] in IDENTITY_VARIABLES


def guarded_program_index(words):
    return next(
        (
            index
            for index, word in enumerate(words)
            if os.path.basename(word) in GUARDED_PROGRAMS
        ),
        None,
    )


def from_guarded_program(words):
    program_index = guarded_program_index(words)
    if program_index is None:
        return []
    return [os.path.basename(words[program_index]), *words[program_index + 1 :]]


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


def is_config_read(after_config):
    if after_config[:1] in (["get"], ["list"]):
        return True
    return any(word in CONFIG_READ_OPTIONS for word in after_config)


def changes_user_section(after_config):
    changes_a_section = any(word in SECTION_COMMANDS for word in after_config)
    return changes_a_section and any(word.lower() == "user" for word in after_config)


def git_config_writes_identity(words):
    if "config" not in words:
        return False
    after_config = words[words.index("config") + 1 :]
    if is_config_read(after_config):
        return False
    if changes_user_section(after_config):
        return True
    return any(word.lower() in IDENTITY_KEYS for word in after_config)


def git_overrides_identity(words):
    for index, word in enumerate(words):
        value = word[2:] if word.startswith("-c") and len(word) > 2 else None
        if word == "-c" and index + 1 < len(words):
            value = words[index + 1]
        if value and value.split("=", 1)[0].lower() in IDENTITY_KEYS:
            return True
        if word == "--author" or word.startswith("--author="):
            return writes_a_commit(words)
    return False


def writes_a_commit(words):
    return any(word in COMMIT_WRITING_SUBCOMMANDS for word in words)


def sets_git_identity(words):
    if words[:1] != ["git"]:
        return False
    return git_config_writes_identity(words) or git_overrides_identity(words)


def segment_denial(segment):
    raw_words = command_words(segment.strip())
    if any(map(sets_identity_variable, assignments_before_program(raw_words))):
        return IDENTITY_DENIAL
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
    if sets_git_identity(words):
        return IDENTITY_DENIAL
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
