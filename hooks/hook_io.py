import json
import os
import sys
import traceback
from collections.abc import Callable
from typing import Literal, Required, TypedDict

from harnesses import OutputShape
from json_values import JsonObject, json_object


class PreToolUseDecision(TypedDict, total=False):
    permissionDecision: Literal["allow", "deny"]
    permissionDecisionReason: str
    updatedInput: JsonObject


class PreToolUseFields(PreToolUseDecision, total=False):
    hookEventName: Required[Literal["PreToolUse"]]


class ContextFields(TypedDict):
    hookEventName: str
    additionalContext: str


class ClaudeOutput(TypedDict):
    hookSpecificOutput: PreToolUseFields | ContextFields


class ClaudeBlock(TypedDict):
    decision: Literal["block"]
    reason: str


class CursorContext(TypedDict):
    additional_context: str


class CursorFollowup(TypedDict):
    followup_message: str


class CursorPermission(TypedDict, total=False):
    permission: Required[Literal["allow", "deny"]]
    user_message: str
    updated_input: JsonObject


type PreToolUseDecider = Callable[[JsonObject], PreToolUseDecision | None]


def read_payload() -> JsonObject:
    return json_object(sys.stdin.read()) or {}


def scratchpad_of(payload: JsonObject) -> str | None:
    scratchpad = payload.get("scratchpad_dir")
    if isinstance(scratchpad, str) and os.path.isabs(scratchpad):
        return scratchpad
    return None


def event_name_of(payload: JsonObject) -> str:
    event = payload.get("hook_event_name")
    return event if isinstance(event, str) else ""


def session_id_of(payload: JsonObject) -> str | None:
    session_id = payload.get("session_id") or payload.get("conversation_id")
    return session_id if isinstance(session_id, str) else None


def agent_session_key(payload: JsonObject) -> str | None:
    session_id = session_id_of(payload)
    agent_id = payload.get("agent_id")
    if session_id is None:
        return None
    if isinstance(agent_id, str) and agent_id:
        return f"{session_id}-{agent_id}"
    return session_id


def is_subagent(payload: JsonObject) -> bool:
    return bool(payload.get("agent_id") or payload.get("subagent_id"))


def cwd_of(payload: JsonObject) -> str:
    cwd = payload.get("cwd")
    return cwd if isinstance(cwd, str) and cwd else os.getcwd()


def pre_tool_use_output(decision: PreToolUseDecision) -> ClaudeOutput:
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", **decision}}


def allowed_with(updated_input: JsonObject) -> PreToolUseDecision:
    return {"permissionDecision": "allow", "updatedInput": updated_input}


def denied(reason: str) -> PreToolUseDecision:
    return {"permissionDecision": "deny", "permissionDecisionReason": reason}


def hook_output(
    event: str, context: str, shape: OutputShape
) -> ClaudeOutput | CursorContext:
    match shape:
        case OutputShape.CURSOR:
            return {"additional_context": context}
        case OutputShape.CLAUDE:
            context_fields: ContextFields = {
                "hookEventName": event,
                "additionalContext": context,
            }
            return {"hookSpecificOutput": context_fields}


def write_context(
    event: str, context: str, shape: OutputShape = OutputShape.CLAUDE
) -> None:
    json.dump(hook_output(event, context, shape), sys.stdout)


def block_output(reason: str, shape: OutputShape) -> ClaudeBlock | CursorFollowup:
    match shape:
        case OutputShape.CURSOR:
            return {"followup_message": reason}
        case OutputShape.CLAUDE:
            return {"decision": "block", "reason": reason}


def write_block(reason: str, shape: OutputShape = OutputShape.CLAUDE) -> None:
    json.dump(block_output(reason, shape), sys.stdout)


def write_pre_tool_use_decision(decide: PreToolUseDecider) -> None:
    decision = decide(read_payload())
    if decision:
        json.dump(pre_tool_use_output(decision), sys.stdout)


def run_pre_tool_use(decide: PreToolUseDecider) -> None:
    run_hook(lambda: write_pre_tool_use_decision(decide))


def run_hook(main: Callable[[], object]) -> None:
    try:
        main()
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        sys.exit(0)
