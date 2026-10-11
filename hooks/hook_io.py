import json
import os
import sys
import traceback

from harnesses import OutputShape


def read_payload():
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def scratchpad_of(payload):
    scratchpad = payload.get("scratchpad_dir")
    if isinstance(scratchpad, str) and os.path.isabs(scratchpad):
        return scratchpad
    return None


def hook_output(event, context, shape):
    match shape:
        case OutputShape.CURSOR:
            return {"additional_context": context}
        case OutputShape.CLAUDE:
            return {
                "hookSpecificOutput": {
                    "hookEventName": event,
                    "additionalContext": context,
                }
            }


def write_context(event, context, shape=OutputShape.CLAUDE):
    json.dump(hook_output(event, context, shape), sys.stdout)


def run_pre_tool_use(decide):
    decision = decide(read_payload())
    if decision:
        output = {"hookEventName": "PreToolUse", **decision}
        json.dump({"hookSpecificOutput": output}, sys.stdout)


def run_hook(main):
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(0)
