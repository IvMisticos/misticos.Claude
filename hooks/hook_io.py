import json
import os
import sys
import traceback
from collections.abc import Callable
from enum import StrEnum
from typing import Literal, Required, TypedDict

from harnesses import OutputShape
from json_values import JsonObject, json_object


class HookEvent(StrEnum):
    SESSION_START = "sessionstart"
    USER_PROMPT_SUBMIT = "userpromptsubmit"
    BEFORE_SUBMIT_PROMPT = "beforesubmitprompt"
    POST_TOOL_USE = "posttooluse"
    POST_TOOL_BATCH = "posttoolbatch"
    AFTER_AGENT_RESPONSE = "afteragentresponse"
    SUBAGENT_START = "subagentstart"
    SUBAGENT_STOP = "subagentstop"
    STOP = "stop"
    SESSION_END = "sessionend"


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


class CursorSubagentPermission(TypedDict, total=False):
    permission: Required[Literal["allow", "deny"]]
    user_message: str


class CursorToolPermission(CursorSubagentPermission, total=False):
    agent_message: str
    updated_input: JsonObject


type PreToolUseDecider = Callable[[JsonObject], PreToolUseDecision | None]
type SubagentStartDecider = Callable[[JsonObject], str | None]


def read_payload() -> JsonObject:
    return json_object(sys.stdin.buffer.read()) or {}


def absolute_path_at(payload: JsonObject, key: str) -> str | None:
    path = payload.get(key)
    if isinstance(path, str) and os.path.isabs(path):
        return path
    return None


def scratchpad_of(payload: JsonObject) -> str | None:
    return absolute_path_at(payload, "scratchpad_dir")


def transcript_path_of(payload: JsonObject) -> str | None:
    return absolute_path_at(payload, "transcript_path")


def event_name_of(payload: JsonObject) -> str:
    event = payload.get("hook_event_name")
    return event if isinstance(event, str) else ""


def hook_event_of(payload: JsonObject) -> HookEvent | None:
    try:
        return HookEvent(event_name_of(payload).lower())
    except ValueError:
        return None


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


def claude_pre_tool_use(decision: PreToolUseDecision) -> ClaudeOutput:
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", **decision}}


def cursor_tool_permission(decision: PreToolUseDecision) -> CursorToolPermission:
    permission: CursorToolPermission = {
        "permission": decision.get("permissionDecision", "allow")
    }
    if "permissionDecisionReason" in decision:
        permission["user_message"] = decision["permissionDecisionReason"]
        permission["agent_message"] = decision["permissionDecisionReason"]
    if "updatedInput" in decision:
        permission["updated_input"] = decision["updatedInput"]
    return permission


def pre_tool_use_output(
    decision: PreToolUseDecision | None, shape: OutputShape
) -> ClaudeOutput | CursorToolPermission | None:
    match shape:
        case OutputShape.CURSOR:
            if not decision:
                return {"permission": "allow"}
            return cursor_tool_permission(decision)
        case OutputShape.CLAUDE:
            return claude_pre_tool_use(decision) if decision else None


def write_pre_tool_use_decision(
    decision: PreToolUseDecision | None, shape: OutputShape
) -> None:
    output = pre_tool_use_output(decision, shape)
    if output:
        json.dump(output, sys.stdout)


def payload_decision[Decision](
    decide: Callable[[JsonObject], Decision | None],
) -> Decision | None:
    try:
        return decide(read_payload())
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        return None


def run_pre_tool_use(
    decide: PreToolUseDecider, shape: OutputShape = OutputShape.CLAUDE
) -> None:
    run_hook(lambda: write_pre_tool_use_decision(payload_decision(decide), shape))


def cursor_subagent_permission(denial: str | None) -> CursorSubagentPermission:
    if denial is None:
        return {"permission": "allow"}
    return {"permission": "deny", "user_message": denial}


def write_cursor_subagent_permission(denial: str | None) -> None:
    json.dump(cursor_subagent_permission(denial), sys.stdout)


def run_cursor_subagent_start(find_denial: SubagentStartDecider) -> None:
    run_hook(lambda: write_cursor_subagent_permission(payload_decision(find_denial)))


def run_hook(main: Callable[[], object]) -> None:
    try:
        main()
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        sys.exit(0)
