#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# [tool.ty.environment]
# root = ["."]
# ///

from harnesses import OutputShape
from hook_io import PreToolUseDecision, denied, run_pre_tool_use
from json_values import JsonObject
from model_cap import outranks


def spawn_decision(payload: JsonObject) -> PreToolUseDecision | None:
    caller = payload.get("model")
    subagent_model = payload.get("subagent_model")
    if not outranks(subagent_model, caller):
        return None
    return denied(
        f"Blocked subagent {payload.get('subagent_type')} on {subagent_model}, "
        f"above the caller's {caller}. Pick one at or below {caller}."
    )


if __name__ == "__main__":
    run_pre_tool_use(spawn_decision, OutputShape.CURSOR)
