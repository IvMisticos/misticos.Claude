#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# [tool.ty.environment]
# root = ["."]
# ///

import argparse
import sys
from collections.abc import Sequence

from harnesses import ContextSource, harness_parser
from hook_io import (
    event_name_of,
    is_subagent,
    read_payload,
    run_hook,
    session_id_of,
    write_context,
)
from json_values import JsonObject
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
    Rules,
    full_copy_messages,
    pointer_reminder,
    rules_at,
)
from transcript import context_tokens, payload_tokens

from agents import ALL_SECTIONS, rule_sections_for

RULES_PATH = str(PLUGIN_ROOT / "INSTRUCTIONS.md")


def is_prompt_event(payload: JsonObject) -> bool:
    return event_name_of(payload).lower() == "userpromptsubmit"


def message_for_part(
    action: Action,
    part: int,
    messages: Sequence[str],
    rules: Rules,
    payload: JsonObject,
) -> str | None:
    if action == Action.POINTER:
        if is_prompt_event(payload):
            return None
        return pointer_reminder(rules) if part == 1 else None
    if action != Action.COPY or not 1 <= part <= len(messages):
        return None
    return messages[part - 1]


def growth_reminder(
    rules: Rules, payload: JsonObject, options: argparse.Namespace
) -> str | None:
    messages = full_copy_messages(rules, GROWN_PREAMBLE)
    session_id = session_id_of(payload)
    if not (messages and session_id):
        return None
    fire = fire_id(event_name_of(payload), payload)
    if not fire and options.part > 1:
        return None
    can_copy = len(messages) <= options.entries and bool(fire or len(messages) == 1)
    if options.harness.context_from == ContextSource.PAYLOAD:
        added = payload_tokens(payload)
        action = claim_action(session_id, fire, can_copy, added_tokens=added)
        return message_for_part(action, options.part, messages, rules, payload)
    transcript_path = payload.get("transcript_path")
    if not (isinstance(transcript_path, str) and transcript_path):
        return None
    tokens = context_tokens(transcript_path, options.harness.context_from)
    if tokens is None:
        return None
    action = claim_action(session_id, fire, can_copy, tokens)
    return message_for_part(action, options.part, messages, rules, payload)


def is_subagent_start(payload: JsonObject) -> bool:
    return is_subagent(payload) or event_name_of(payload).lower() == "subagentstart"


def session_start_reminder(
    rules: Rules, payload: JsonObject, options: argparse.Namespace
) -> str | None:
    is_subagent = is_subagent_start(payload)
    session_id = session_id_of(payload)
    if options.part == 1 and session_id and not is_subagent:
        forget_baseline(session_id)
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
    return message_for_part(Action.COPY, options.part, messages, rules, payload)


def reminder_for(
    event: str, payload: JsonObject, options: argparse.Namespace
) -> str | None:
    rules = rules_at(RULES_PATH, options.harness.model_names)
    if event.lower() in ("sessionstart", "subagentstart"):
        return session_start_reminder(rules, payload, options)
    if is_subagent(payload):
        return None
    return growth_reminder(rules, payload, options)


def parsed_options(argv: Sequence[str]) -> argparse.Namespace:
    parser = harness_parser()
    parser.add_argument("part", type=int, nargs="?", default=1)
    parser.add_argument("entries", type=int, nargs="?")
    options = parser.parse_args(argv)
    if options.entries is None:
        options.entries = options.part
    return options


def main() -> None:
    options = parsed_options(sys.argv[1:])
    payload = read_payload()
    event = event_name_of(payload)
    if not event:
        return
    reminder = reminder_for(event, payload, options)
    if reminder:
        write_context(event, reminder, options.harness.output_shape)


if __name__ == "__main__":
    run_hook(main)
