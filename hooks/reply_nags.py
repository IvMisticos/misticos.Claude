#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///

import os
import uuid
from typing import NamedTuple

from harnesses import ReplyHistory, harness_parser
from hook_io import read_payload, run_hook, write_context
from reply_history import (
    EventLog,
    Reply,
    Window,
    parsed_event_log,
    transcript_history,
    window_under_review,
    without_trailing_prompts,
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
    "One of your recent messages had at least {length} characters outside "
    "code and links. Don't resend it, but from now on keep your messages "
    "briefer and cut them as your instructions say."
)
REPEATED_UPDATES = (
    "You sent {count} messages in a row with no user message in between. "
    "Send no progress updates unless the user asked for them or something needs "
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
    window_replies: int = 0
    nagged_at: int = 0


class DueNags(NamedTuple):
    long_reply: str = ""
    repeated_updates: str = ""

    def merged_over(self, older):
        return DueNags(
            self.long_reply or older.long_reply,
            self.repeated_updates or older.repeated_updates,
        )

    def texts(self):
        return [nag for nag in self if nag]


class NagState(NamedTuple):
    memory: NagMemory = NagMemory()
    log: EventLog = EventLog()
    pending_nags: DueNags = DueNags()

    def to_json(self):
        return {
            "memory": self.memory._asdict(),
            "log": self.log.to_json(),
            "pending_nags": self.pending_nags._asdict(),
        }


def parsed_memory(stored):
    try:
        memory = NagMemory(**dict_or_empty(stored))
    except TypeError:
        return NagMemory()
    valid = (
        isinstance(memory.seen_reply, str)
        and isinstance(memory.window, str)
        and isinstance(memory.window_replies, int)
        and isinstance(memory.nagged_at, int)
    )
    return memory if valid else NagMemory()


def parsed_pending_nags(stored):
    try:
        nags = DueNags(**dict_or_empty(stored))
    except TypeError:
        return DueNags()
    return nags if all(isinstance(nag, str) for nag in nags) else DueNags()


def parsed_state(stored):
    stored = dict_or_empty(stored)
    return NagState(
        parsed_memory(stored.get("memory")),
        parsed_event_log(stored.get("log")),
        parsed_pending_nags(stored.get("pending_nags")),
    )


def unseen_replies(replies, seen_reply):
    ids = [reply.id for reply in replies]
    if seen_reply not in ids:
        return replies
    return replies[ids.index(seen_reply) + 1 :]


def long_reply_nag(unseen):
    long_replies = [reply for reply in unseen if reply.prose_length > PROSE_LIMIT]
    if not long_replies:
        return None
    return LONG_REPLY.format(length=long_replies[-1].prose_length)


def repeated_updates_nag(history, memory, unseen):
    remembered = Window(memory.window, memory.window_replies)
    window = window_under_review(history, remembered, len(unseen))
    if window is None:
        return None, memory
    nagged_at = memory.nagged_at if memory.window == window.prompt_id else 0
    due_at = nagged_at + MESSAGES_BETWEEN_NAGS if nagged_at else FIRST_NAG_AT_MESSAGES
    count = window.reply_count
    memory = memory._replace(window=window.prompt_id, window_replies=count)
    if count < due_at:
        return None, memory._replace(nagged_at=nagged_at)
    return REPEATED_UPDATES.format(count=count), memory._replace(nagged_at=count)


def due_nags(history, memory):
    replies = [item for item in history if isinstance(item, Reply)]
    unseen = unseen_replies(replies, memory.seen_reply)
    repeated_updates, memory = repeated_updates_nag(history, memory, unseen)
    if replies:
        memory = memory._replace(seen_reply=replies[-1].id)
    return DueNags(long_reply_nag(unseen) or "", repeated_updates or ""), memory


def nags_from_transcript(event, payload, state):
    if event not in NAG_EVENTS:
        return [], state
    history = transcript_history(payload.get("transcript_path"))
    if event not in PROMPT_EVENTS:
        nags, memory = due_nags(history, state.memory)
        return nags.texts(), state._replace(memory=memory)
    nags, memory = due_nags(without_trailing_prompts(history), state.memory)
    memory = memory._replace(
        window=f"submitted-{uuid.uuid4()}", window_replies=0, nagged_at=0
    )
    return nags.texts(), state._replace(memory=memory)


def nags_from_events(event, payload, state):
    log = state.log
    reply_text = payload.get(REPLY_TEXT_FIELD_BY_EVENT.get(event))
    if isinstance(reply_text, str) and reply_text.strip():
        log = log.with_reply(reply_text)
    if event not in NAG_EVENTS | PROMPT_EVENTS:
        return [], state._replace(log=log)
    due, memory = due_nags(log.history, state.memory)
    log = log.starting_at(memory.window)
    if event in PROMPT_EVENTS:
        log = log.with_prompt()
    if event in NAG_EVENTS:
        return due.merged_over(state.pending_nags).texts(), NagState(memory, log)
    return [], NagState(memory, log, due.merged_over(state.pending_nags))


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
        if options.harness.reply_history == ReplyHistory.TRANSCRIPT
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
