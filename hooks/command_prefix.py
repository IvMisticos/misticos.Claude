#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///

import argparse
import json
import os
import sys

from session_environment import session_environment_command


def shell_tool_input(payload):
    tool_input = payload.get("tool_input")
    if isinstance(tool_input, dict) and isinstance(tool_input.get("command"), str):
        return tool_input
    return None


def with_session_environment(command):
    return f"{session_environment_command()}; {command}"


def rewritten_tool_call(tool_input, shape):
    command = with_session_environment(tool_input["command"])
    updated_input = {**tool_input, "command": command}
    if shape == "cursor":
        return {"permission": "allow", "updated_input": updated_input}
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "updatedInput": updated_input,
        }
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-shape", choices=("claude", "cursor"), default="claude"
    )
    options = parser.parse_args()
    if os.name != "posix":
        return
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        return
    tool_input = shell_tool_input(payload)
    if tool_input:
        json.dump(rewritten_tool_call(tool_input, options.output_shape), sys.stdout)


if __name__ == "__main__":
    main()
