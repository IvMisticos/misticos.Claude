#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///

import json
import sys

from model_tiers import outranks

ALLOW = {"permission": "allow"}


def spawn_decision(payload):
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


def main():
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        decision = spawn_decision(payload)
    except Exception:
        decision = ALLOW
    json.dump(decision, sys.stdout)


if __name__ == "__main__":
    main()
