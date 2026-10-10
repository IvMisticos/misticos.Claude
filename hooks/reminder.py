#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///

import sys
from pathlib import Path

from harnesses import add_harness_argument
from hook_io import QuietArgumentParser, read_payload, run_hook, write_context
from reminder_baselines import (
    COPY,
    POINTER,
    claim_action,
    fire_id,
    forget_baseline,
)
from rules_copy import (
    GROWN_PREAMBLE,
    SESSION_START_PREAMBLE,
    full_copy_messages,
    pointer_reminder,
    rules_at,
)
from transcript import context_tokens, payload_tokens, transcript_fits_in_tail

RULES_PATH = str(Path(__file__).resolve().parent.parent / "INSTRUCTIONS.md")


def message_for_part(action, part, messages, rules):
    if action == POINTER:
        return pointer_reminder(rules) if part == 1 else None
    if action != COPY or not 1 <= part <= len(messages):
        return None
    return messages[part - 1]


def growth_reminder(rules, payload, options):
    messages = full_copy_messages(rules, GROWN_PREAMBLE)
    session_id = payload.get("session_id") or payload.get("conversation_id")
    if not (messages and session_id):
        return None
    fire = fire_id(event_name(payload), payload)
    if not fire and options.part > 1:
        return None
    can_copy = len(messages) <= options.entries and bool(fire or len(messages) == 1)
    if options.harness.context_from == "payload":
        added = payload_tokens(payload)
        action = claim_action(session_id, fire, can_copy, added_tokens=added)
        return message_for_part(action, options.part, messages, rules)
    transcript_path = payload.get("transcript_path")
    if not transcript_path:
        return None
    tokens = context_tokens(transcript_path, options.harness.context_from)
    if tokens is None:
        if options.part != 1 or event_name(payload).lower() != "userpromptsubmit":
            return None
        return (
            pointer_reminder(rules)
            if transcript_fits_in_tail(transcript_path)
            else None
        )
    action = claim_action(session_id, fire, can_copy, tokens)
    return message_for_part(action, options.part, messages, rules)


def event_name(payload):
    return str(payload.get("hook_event_name"))


def session_start_reminder(rules, payload, options):
    is_subagent = payload.get("agent_id") or payload.get("subagent_id")
    if options.part == 1 and payload.get("session_id") and not is_subagent:
        forget_baseline(payload["session_id"])
    messages = full_copy_messages(rules, SESSION_START_PREAMBLE)
    if len(messages) > options.entries:
        return pointer_reminder(rules) if options.part == 1 else None
    return message_for_part(COPY, options.part, messages, rules)


def is_skipped_subagent(event, payload, options):
    starts_subagent = event.lower() == "subagentstart"
    agent_type = payload.get("agent_type")
    return starts_subagent and agent_type in options.harness.skipped_agent_types


def reminder_for(event, payload, options):
    if is_skipped_subagent(event, payload, options):
        return None
    rules = rules_at(RULES_PATH, options.harness.model_names)
    if event.lower() in ("sessionstart", "subagentstart"):
        return session_start_reminder(rules, payload, options)
    if payload.get("agent_id") or payload.get("subagent_id"):
        return None
    return growth_reminder(rules, payload, options)


def parsed_options(argv):
    parser = QuietArgumentParser(add_help=False)
    parser.add_argument("part", type=int, nargs="?", default=1)
    parser.add_argument("entries", type=int, nargs="?")
    add_harness_argument(parser)
    options = parser.parse_args(argv)
    if options.entries is None:
        options.entries = options.part
    return options


def main():
    options = parsed_options(sys.argv[1:])
    payload = read_payload()
    event = payload.get("hook_event_name")
    if not event:
        return
    reminder = reminder_for(event, payload, options)
    if reminder:
        write_context(event, reminder, options.harness.output_shape)


if __name__ == "__main__":
    run_hook(main)
