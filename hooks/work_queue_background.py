#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///

import os
import shlex

from model_cap import run_pre_tool_use

if os.name == "posix":
    from work_queue import build_would_wait, queues


def command_tokens(command):
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError:
        tokens = command.split()
    for token in tokens:
        if any(character.isspace() for character in token):
            yield from command_tokens(token)
        else:
            yield token


def runs_benchmark(words):
    return any(
        os.path.basename(word) == "queue" and words[index + 1 : index + 2] == ["bench"]
        for index, word in enumerate(words)
    )


def runs_queued_tool(words):
    return any(
        queues(os.path.basename(word), words[index + 1 :])
        for index, word in enumerate(words)
    )


def would_wait(command):
    words = list(command_tokens(command))
    return runs_benchmark(words) or (runs_queued_tool(words) and build_would_wait())


def decide(payload):
    tool_input = payload.get("tool_input") or {}
    if tool_input.get("run_in_background"):
        return None
    if not would_wait(str(tool_input.get("command") or "")):
        return None
    return {"updatedInput": {**tool_input, "run_in_background": True}}


if __name__ == "__main__" and os.name == "posix":
    run_pre_tool_use(decide)
