#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///

import sys

from harnesses import ContextSource, harness_parser
from hook_io import read_payload, run_hook, write_context
from plugin_paths import PLUGIN_ROOT
from reminder_baselines import (
    Action,
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

from agents import ALL_SECTIONS, rule_sections_for

RULES_PATH = str(PLUGIN_ROOT / "INSTRUCTIONS.md")


def message_for_part(action, part, messages, rules):
    if action == Action.POINTER:
        return pointer_reminder(rules) if part == 1 else None
    if action != Action.COPY or not 1 <= part <= len(messages):
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
    if options.harness.context_from == ContextSource.PAYLOAD:
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


def is_subagent_start(payload):
    return bool(
        payload.get("agent_id")
        or payload.get("subagent_id")
        or event_name(payload).lower() == "subagentstart"
    )


def session_start_reminder(rules, payload, options):
    is_subagent = is_subagent_start(payload)
    if options.part == 1 and payload.get("session_id") and not is_subagent:
        forget_baseline(payload["session_id"])
    sections = (
        rule_sections_for(payload.get("agent_type")) if is_subagent else ALL_SECTIONS
    )
    if not sections:
        return None
    messages = full_copy_messages(
        rules, SESSION_START_PREAMBLE, ALL_SECTIONS - sections
    )
    if len(messages) > options.entries:
        return pointer_reminder(rules) if options.part == 1 else None
    return message_for_part(Action.COPY, options.part, messages, rules)


def reminder_for(event, payload, options):
    rules = rules_at(RULES_PATH, options.harness.model_names)
    if event.lower() in ("sessionstart", "subagentstart"):
        return session_start_reminder(rules, payload, options)
    if payload.get("agent_id") or payload.get("subagent_id"):
        return None
    return growth_reminder(rules, payload, options)


def parsed_options(argv):
    parser = harness_parser()
    parser.add_argument("part", type=int, nargs="?", default=1)
    parser.add_argument("entries", type=int, nargs="?")
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
