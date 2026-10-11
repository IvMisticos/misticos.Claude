#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///

import os
from typing import NamedTuple

from harnesses import harness_parser
from hook_io import read_payload, run_hook, write_context
from reply_history import (
    EventLog,
    Reply,
    parsed_event_log,
    transcript_history,
    window_under_review,
)
from session_state import (
    STATE_ROOT,
    locked_session_file,
    read_json,
    write_json,
)
from transcript import dict_or_empty

PROSE_LIMIT = 300
FIRST_NAG_AT_MESSAGES = 2
MESSAGES_BETWEEN_NAGS = 6
STATE_DIR = os.path.join(STATE_ROOT, "reply-nags")
LONG_REPLY = (
    "One of your messages had {length} characters outside code and links, "
    "past the {limit} limit. Cut what doesn't change what the user does next."
)
REPEATED_UPDATES = (
    "You sent {count} messages in a row with no user message in between. "
    "Send no more updates unless the user asked for them or something needs "
    "their decision."
)
REPLY_TEXT_FIELD_BY_EVENT = {
    "stop": "last_assistant_message",
    "afteragentresponse": "text",
}
PROMPT_EVENTS = frozenset({"userpromptsubmit", "beforesubmitprompt"})
NAG_EVENTS = frozenset({"userpromptsubmit", "posttoolbatch", "posttooluse"})


class NagMemory(NamedTuple):
    seen_reply: str = ""
    window: str = ""
    nagged_at: int = 0


class NagState(NamedTuple):
    memory: NagMemory = NagMemory()
    log: EventLog = EventLog()

    def to_json(self):
        return {"memory": self.memory._asdict(), "log": self.log.to_json()}


def parsed_memory(stored):
    try:
        memory = NagMemory(**dict_or_empty(stored))
    except TypeError:
        return NagMemory()
    valid = (
        isinstance(memory.seen_reply, str)
        and isinstance(memory.window, str)
        and isinstance(memory.nagged_at, int)
    )
    return memory if valid else NagMemory()


def parsed_state(stored):
    stored = dict_or_empty(stored)
    return NagState(
        parsed_memory(stored.get("memory")), parsed_event_log(stored.get("log"))
    )


def unseen_replies(replies, seen_reply):
    ids = [reply.id for reply in replies]
    if seen_reply not in ids:
        return replies
    return replies[ids.index(seen_reply) + 1 :]


def long_reply_nag(history, memory):
    replies = [item for item in history if isinstance(item, Reply)]
    if not replies:
        return None, memory
    long_replies = [
        reply
        for reply in unseen_replies(replies, memory.seen_reply)
        if reply.prose_length > PROSE_LIMIT
    ]
    memory = memory._replace(seen_reply=replies[-1].id)
    if not long_replies:
        return None, memory
    nag = LONG_REPLY.format(length=long_replies[-1].prose_length, limit=PROSE_LIMIT)
    return nag, memory


def repeated_updates_nag(history, memory):
    window = window_under_review(history, memory.window)
    if window is None:
        return None, memory
    nagged_at = memory.nagged_at if memory.window == window.prompt_id else 0
    due_at = nagged_at + MESSAGES_BETWEEN_NAGS if nagged_at else FIRST_NAG_AT_MESSAGES
    count = len(window.replies)
    if count < due_at:
        return None, memory._replace(window=window.prompt_id, nagged_at=nagged_at)
    nag = REPEATED_UPDATES.format(count=count)
    return nag, memory._replace(window=window.prompt_id, nagged_at=count)


def due_nags(history, memory):
    long_reply, memory = long_reply_nag(history, memory)
    repeated_updates, memory = repeated_updates_nag(history, memory)
    return [nag for nag in (long_reply, repeated_updates) if nag], memory


def nags_from_transcript(event, payload, state):
    if event not in NAG_EVENTS:
        return [], state
    history = transcript_history(payload.get("transcript_path"))
    nags, memory = due_nags(history, state.memory)
    return nags, state._replace(memory=memory)


def nags_from_events(event, payload, state):
    log = state.log
    reply_text = payload.get(REPLY_TEXT_FIELD_BY_EVENT.get(event))
    if isinstance(reply_text, str) and reply_text.strip():
        log = log.with_reply(reply_text)
    nags, memory = [], state.memory
    if event in NAG_EVENTS:
        nags, memory = due_nags(log.history, memory)
        log = log.starting_at(memory.window)
    if event in PROMPT_EVENTS:
        log = log.with_prompt()
    return nags, NagState(memory, log)


def is_subagent(payload):
    return bool(payload.get("agent_id") or payload.get("subagent_id"))


def main():
    options = harness_parser().parse_args()
    payload = read_payload()
    event = str(payload.get("hook_event_name") or "")
    session_id = payload.get("session_id") or payload.get("conversation_id")
    if not (event and isinstance(session_id, str)) or is_subagent(payload):
        return
    nags_for = (
        nags_from_transcript
        if options.harness.reply_history == "transcript"
        else nags_from_events
    )
    with locked_session_file(STATE_DIR, session_id) as state_file:
        state = parsed_state(read_json(state_file))
        nags, state = nags_for(event.lower(), payload, state)
        write_json(state_file, state.to_json())
    if nags:
        write_context(event, " ".join(nags), options.harness.output_shape)


if __name__ == "__main__":
    run_hook(main)
