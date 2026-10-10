#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///

import json
import sys

from hook_io import hook_output, read_payload

AGENT_ROLES_NOTE = (
    "Start workers as misticos agents, picked by the role in their "
    "descriptions. Use a built-in agent type only when no role fits."
)


def main():
    payload = read_payload()
    event = payload.get("hook_event_name")
    if event:
        json.dump(hook_output(event, AGENT_ROLES_NOTE, "claude"), sys.stdout)


if __name__ == "__main__":
    main()
