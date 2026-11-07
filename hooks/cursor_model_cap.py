#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# [tool.ty.environment]
# root = ["."]
# ///

from hook_io import run_cursor_subagent_start
from json_values import JsonObject
from model_cap import over_cap, parsed_model


def spawn_denial(payload: JsonObject) -> str | None:
    subagent_model = parsed_model(payload.get("subagent_model"))
    caller = parsed_model(payload.get("model"))
    over = over_cap(subagent_model, caller)
    if over is None:
        return None
    capped, limit = over
    return (
        f"Blocked subagent {payload.get('subagent_type')} on {capped.name}, "
        f"above the caller's {limit.name}. Pick one at or below {limit.name}."
    )


if __name__ == "__main__":
    run_cursor_subagent_start(spawn_denial)
