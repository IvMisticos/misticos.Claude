#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# [tool.ty.environment]
# root = ["."]
# ///

import os

from harnesses import harness_parser
from hook_io import allowed_with, read_payload, run_hook, write_pre_tool_use_decision
from json_values import JsonObject, dict_or_empty
from session_environment import session_environment_command


def prefixed_input(tool_input: JsonObject) -> JsonObject | None:
    command = tool_input.get("command")
    if not isinstance(command, str):
        return None
    return {**tool_input, "command": f"{session_environment_command()}; {command}"}


def main() -> None:
    options = harness_parser().parse_args()
    if os.name != "posix":
        return
    updated_input = prefixed_input(dict_or_empty(read_payload().get("tool_input")))
    if updated_input:
        decision = allowed_with(updated_input)
        write_pre_tool_use_decision(decision, options.harness.output_shape)


if __name__ == "__main__":
    run_hook(main)
