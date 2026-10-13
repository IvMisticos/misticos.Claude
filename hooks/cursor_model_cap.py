#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# [tool.ty.environment]
# root = ["."]
# ///

import json
import sys

from hook_io import CursorPermission, read_payload
from json_values import JsonObject
from model_cap import outranks

ALLOW: CursorPermission = {"permission": "allow"}


def spawn_decision(payload: JsonObject) -> CursorPermission:
    caller = payload.get("model")
    subagent_model = payload.get("subagent_model")
    if not outranks(subagent_model, caller):
        return ALLOW
    return {
        "permission": "deny",
        "user_message": (
            f"Blocked subagent {payload.get('subagent_type')} on {subagent_model}, "
            f"above the caller's {caller}. Pick one at or below {caller}."
        ),
    }


def main() -> None:
    try:
        payload = read_payload()
    except (OSError, UnicodeDecodeError):
        payload = {}
    json.dump(spawn_decision(payload), sys.stdout)


if __name__ == "__main__":
    main()
