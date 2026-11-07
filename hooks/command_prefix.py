#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# [tool.ty.environment]
# root = ["."]
# ///

import os

from harnesses import harness_parser
from hook_io import PreToolUseDecision, allowed_with, run_hook, run_pre_tool_use
from json_values import JsonObject, dict_or_empty
from session_environment import session_environment_command


def prefixed_input(tool_input: JsonObject) -> JsonObject | None:
    command = tool_input.get("command")
    if not isinstance(command, str):
        return None
    return {**tool_input, "command": f"{session_environment_command()}; {command}"}


def prefixed_command(payload: JsonObject) -> PreToolUseDecision | None:
    if os.name != "posix":
        return None
    updated_input = prefixed_input(dict_or_empty(payload.get("tool_input")))
    return allowed_with(updated_input) if updated_input else None


def main() -> None:
    options = harness_parser().parse_args()
    run_pre_tool_use(prefixed_command, options.harness.output_shape)


if __name__ == "__main__":
    run_hook(main)
