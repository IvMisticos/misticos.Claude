#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# [tool.ty.environment]
# root = ["."]
# ///

from hook_io import run_cursor_subagent_start
from json_values import JsonObject
from model_cap import denial_reason, parsed_model


def spawn_denial(payload: JsonObject) -> str | None:
    subject = f"Subagent {payload.get('subagent_type')}"
    subagent_model = parsed_model(payload.get("subagent_model"))
    caller = parsed_model(payload.get("model"))
    return denial_reason(subject, subagent_model, caller)


if __name__ == "__main__":
    run_cursor_subagent_start(spawn_denial)
