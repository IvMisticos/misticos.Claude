#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# [tool.ty.environment]
# root = ["."]
# ///

from hook_io import run_cursor_subagent_start
from json_values import JsonObject
from model_cap import outranks, parsed_model


def spawn_denial(payload: JsonObject) -> str | None:
    caller = payload.get("model")
    subagent_model = payload.get("subagent_model")
    if not outranks(parsed_model(subagent_model), parsed_model(caller)):
        return None
    return (
        f"Blocked subagent {payload.get('subagent_type')} on {subagent_model}, "
        f"above the caller's {caller}. Pick one at or below {caller}."
    )


if __name__ == "__main__":
    run_cursor_subagent_start(spawn_denial)
