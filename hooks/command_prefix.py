#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# [tool.ty.environment]
# root = ["."]
# ///

import json
import os
import sys

from harnesses import OutputShape, harness_parser
from hook_io import (
    ClaudeOutput,
    CursorPermission,
    allowed_with,
    pre_tool_use_output,
    read_payload,
    run_hook,
)
from json_values import JsonObject, dict_or_empty
from session_environment import session_environment_command


def rewritten_tool_call(
    payload: JsonObject, shape: OutputShape
) -> CursorPermission | ClaudeOutput | None:
    tool_input = dict_or_empty(payload.get("tool_input"))
    command = tool_input.get("command")
    if not isinstance(command, str):
        return None
    prefixed = f"{session_environment_command()}; {command}"
    updated_input = {**tool_input, "command": prefixed}
    match shape:
        case OutputShape.CURSOR:
            return {"permission": "allow", "updated_input": updated_input}
        case OutputShape.CLAUDE:
            return pre_tool_use_output(allowed_with(updated_input))


def main() -> None:
    options = harness_parser().parse_args()
    if os.name != "posix":
        return
    tool_call = rewritten_tool_call(read_payload(), options.harness.output_shape)
    if tool_call:
        json.dump(tool_call, sys.stdout)


if __name__ == "__main__":
    run_hook(main)
