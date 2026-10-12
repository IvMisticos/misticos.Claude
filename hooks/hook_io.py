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


def hook_specific_output(event, fields):
    return {"hookSpecificOutput": {"hookEventName": event, **fields}}


def pre_tool_use_output(decision):
    return hook_specific_output("PreToolUse", decision)


def allowed_with(updated_input):
    return {"permissionDecision": "allow", "updatedInput": updated_input}


def denied(reason):
    return {"permissionDecision": "deny", "permissionDecisionReason": reason}


def hook_output(event, context, shape):
    match shape:
        case OutputShape.CURSOR:
            return {"additional_context": context}
        case OutputShape.CLAUDE:
            return hook_specific_output(event, {"additionalContext": context})


def write_context(event, context, shape=OutputShape.CLAUDE):
    json.dump(hook_output(event, context, shape), sys.stdout)


def block_output(reason, shape):
    match shape:
        case OutputShape.CURSOR:
            return {"followup_message": reason}
        case OutputShape.CLAUDE:
            return {"decision": "block", "reason": reason}


def write_block(reason, shape=OutputShape.CLAUDE):
    json.dump(block_output(reason, shape), sys.stdout)


def run_pre_tool_use(decide):
    decision = decide(read_payload())
    if decision:
        json.dump(pre_tool_use_output(decision), sys.stdout)


def run_hook(main):
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(0)
