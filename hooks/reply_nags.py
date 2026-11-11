#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# [tool.ty.environment]
# root = ["."]
# ///

import copy
import uuid
from collections.abc import Sequence
from typing import NamedTuple

from harnesses import ReplyHistory, harness_parser
from hook_io import (
    HookEvent,
    event_name_of,
    hook_event_of,
    is_subagent,
    read_payload,
    run_hook,
    session_id_of,
    transcript_path_of,
    write_context,
)
from json_values import JsonObject, JsonValue
from plugin_paths import DATA_ROOT
from reply_history import (
    EventLog,
    Prompt,
    Reply,
    Window,
    transcript_history,
    window_under_review,
)
from session_state import locked_session_file, read_record, write_record

FIRST_NAG_AT_MESSAGES = 3
MESSAGES_BETWEEN_NAGS = 6
STATE_DIR = DATA_ROOT / "reply-nags"
REPEATED_UPDATES = (
    "You sent {count} messages in a row with no user message in between. "
    "Send no progress updates unless the user asked for them or something needs "
    "their decision."
)
REPLY_TEXT_FIELD_BY_EVENT = {
    HookEvent.STOP: "last_assistant_message",
    HookEvent.AFTER_AGENT_RESPONSE: "text",
}
PROMPT_EVENTS = frozenset(
    {HookEvent.USER_PROMPT_SUBMIT, HookEvent.BEFORE_SUBMIT_PROMPT}
)
WAKE_PROMPT_STARTS = (
    "<task-notification>",
    "<agent-message",
    "Another Claude session sent a message",
)
NAG_EVENTS = frozenset(
    {HookEvent.USER_PROMPT_SUBMIT, HookEvent.POST_TOOL_BATCH, HookEvent.POST_TOOL_USE}
)


class NagMemory(NamedTuple):
    seen_reply: str = ""
    window: str = ""
    window_replies: int = 0
    nagged_at: int = 0
    submitted_prompt: str = ""


class NagState(NamedTuple):
    memory: NagMemory = NagMemory()
    log: EventLog = EventLog()
    pending_nag: str = ""


def unseen_replies(replies: list[Reply], seen_reply: str) -> list[Reply]:
    ids = [reply.id for reply in replies]
    if seen_reply not in ids:
        return replies
    return replies[ids.index(seen_reply) + 1 :]


def remembered_window(memory: NagMemory) -> Window:
    if memory.submitted_prompt:
        return Window(memory.submitted_prompt, 0)
    return Window(memory.window, memory.window_replies)


def repeated_updates_nag(
    history: Sequence[Prompt | Reply], memory: NagMemory, unseen: list[Reply]
) -> tuple[str, NagMemory]:
    window = window_under_review(history, remembered_window(memory), len(unseen))
    if window is None:
        return "", memory
    nagged_at = memory.nagged_at if memory.window == window.prompt_id else 0
    due_at = nagged_at + MESSAGES_BETWEEN_NAGS if nagged_at else FIRST_NAG_AT_MESSAGES
    count = window.reply_count
    memory = copy.replace(
        memory, window=window.prompt_id, window_replies=count, submitted_prompt=""
    )
    if count < due_at:
        return "", copy.replace(memory, nagged_at=nagged_at)
    return REPEATED_UPDATES.format(count=count), copy.replace(memory, nagged_at=count)


def due_nags(
    history: Sequence[Prompt | Reply], memory: NagMemory
) -> tuple[str, NagMemory]:
    replies = [item for item in history if isinstance(item, Reply)]
    unseen = unseen_replies(replies, memory.seen_reply)
    nag, memory = repeated_updates_nag(history, memory, unseen)
    if replies:
        memory = copy.replace(memory, seen_reply=replies[-1].id)
    return nag, memory


def nags_from_transcript(
    event: HookEvent, payload: JsonObject, state: NagState
) -> tuple[list[str], NagState]:
    if event not in NAG_EVENTS:
        return [], state
    transcript_path = transcript_path_of(payload)
    history = transcript_history(transcript_path) if transcript_path else []
    nag, memory = due_nags(history, state.memory)
    if event in PROMPT_EVENTS and not is_wake_prompt(payload.get("prompt")):
        memory = copy.replace(memory, submitted_prompt=submitted_prompt_id(payload))
    return [nag] if nag else [], copy.replace(state, memory=memory)


def submitted_prompt_id(payload: JsonObject) -> str:
    prompt_id = payload.get("prompt_id")
    if isinstance(prompt_id, str) and prompt_id:
        return prompt_id
    return f"submitted-{uuid.uuid4()}"


def is_wake_prompt(prompt: JsonValue) -> bool:
    return isinstance(prompt, str) and prompt.lstrip().startswith(WAKE_PROMPT_STARTS)


def nags_from_events(
    event: HookEvent, payload: JsonObject, state: NagState
) -> tuple[list[str], NagState]:
    log = state.log
    reply_field = REPLY_TEXT_FIELD_BY_EVENT.get(event)
    reply_text = payload.get(reply_field) if reply_field else None
    if isinstance(reply_text, str) and reply_text.strip():
        log = log.with_reply()
    if event not in NAG_EVENTS | PROMPT_EVENTS:
        return [], copy.replace(state, log=log)
    due, memory = due_nags(log.history, state.memory)
    log = log.starting_at(memory.window)
    if event in PROMPT_EVENTS:
        log = log.with_prompt()
    if event in NAG_EVENTS:
        nag = due or state.pending_nag
        return [nag] if nag else [], NagState(memory, log)
    return [], NagState(memory, log, due or state.pending_nag)


def main() -> None:
    options = harness_parser().parse_args()
    payload = read_payload()
    event = hook_event_of(payload)
    session_id = session_id_of(payload)
    if not (event and session_id) or is_subagent(payload):
        return
    nags_for = (
        nags_from_transcript
        if options.harness.reply_history == ReplyHistory.TRANSCRIPT
        else nags_from_events
    )
    with locked_session_file(STATE_DIR, session_id) as state_file:
        nags, state = nags_for(event, payload, read_record(state_file, NagState()))
        write_record(state_file, state)
    if nags:
        event_name = event_name_of(payload)
        write_context(event_name, " ".join(nags), options.harness.output_shape)


if __name__ == "__main__":
    run_hook(main)
