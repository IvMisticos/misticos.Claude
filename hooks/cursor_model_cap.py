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
    caller = parsed_model(payload.get("model"))
    subagent_model = parsed_model(payload.get("subagent_model"))
    if subagent_model is None or caller is None or not outranks(subagent_model, caller):
        return None
    return (
        f"Blocked subagent {payload.get('subagent_type')} on {subagent_model.name}, "
        f"above the caller's {caller.name}. Pick one at or below {caller.name}."
    )


if __name__ == "__main__":
    run_cursor_subagent_start(spawn_denial)
