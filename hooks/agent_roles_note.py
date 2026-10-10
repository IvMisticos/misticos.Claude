#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///

import json
import sys

from reminder import hook_output

AGENT_ROLES_NOTE = (
    "Start workers as misticos agents, picked by role. Each one pins its model "
    "and cache lifetime. misticos:scout searches and filters large data, on "
    "Haiku. misticos:reviewer reviews, on Opus. misticos:coder makes a simple, "
    "specific change, on Sonnet. misticos:engineer takes open-ended work, on "
    "Opus. Use a built-in agent type only when no role fits."
)


def main():
    payload = json.loads(sys.stdin.read() or "{}")
    event = payload.get("hook_event_name")
    if event and not payload.get("agent_id"):
        json.dump(hook_output(event, AGENT_ROLES_NOTE, "claude"), sys.stdout)


if __name__ == "__main__":
    main()
