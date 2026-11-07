#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# [tool.ty.environment]
# root = ["."]
# ///

import sys
from collections.abc import Sequence
from typing import NamedTuple

from harnesses import ContextSource, Harness, harness_parser
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
from json_values import JsonObject
from plugin_paths import PLUGIN_ROOT
from reminder_baselines import (
    Action,
    ContextAdded,
    ContextTotal,
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
REMINDER_PARTS = 4


class Options(NamedTuple):
    part: int
    harness: Harness


def is_prompt_event(payload: JsonObject) -> bool:
    return hook_event_of(payload) == HookEvent.USER_PROMPT_SUBMIT


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


def measured_context(
    payload: JsonObject, source: ContextSource
) -> ContextTotal | ContextAdded | None:
    if source == ContextSource.PAYLOAD:
        return ContextAdded(payload_tokens(payload))
    transcript_path = transcript_path_of(payload)
    if transcript_path is None:
        return None
    tokens = context_tokens(transcript_path, source)
    return None if tokens is None else ContextTotal(tokens)


def growth_reminder(rules: Rules, payload: JsonObject, options: Options) -> str | None:
    messages = full_copy_messages(rules, GROWN_PREAMBLE)
    session_id = session_id_of(payload)
    if not (messages and session_id):
        return None
    fire = fire_id(event_name_of(payload), payload)
    if not fire and options.part > 1:
        return None
    context = measured_context(payload, options.harness.context_from)
    if context is None:
        return None
    can_copy = len(messages) <= REMINDER_PARTS and bool(fire or len(messages) == 1)
    action = claim_action(session_id, fire, can_copy, context)
    return message_for_part(action, options.part, messages, rules, payload)


def is_subagent_start(payload: JsonObject) -> bool:
    return is_subagent(payload) or hook_event_of(payload) == HookEvent.SUBAGENT_START


def session_start_reminder(
    rules: Rules, payload: JsonObject, options: Options
) -> str | None:
    for_subagent = is_subagent_start(payload)
    session_id = session_id_of(payload)
    if options.part == 1 and session_id and not for_subagent:
        forget_baseline(session_id)
    sections = (
        rule_sections_for(payload.get("agent_type")) if for_subagent else ALL_SECTIONS
    )
    if not sections:
        return None
    messages = full_copy_messages(
        rules, SESSION_START_PREAMBLE, ALL_SECTIONS - sections
    )
    if len(messages) > REMINDER_PARTS:
        return pointer_reminder(rules) if options.part == 1 else None
    return message_for_part(Action.COPY, options.part, messages, rules, payload)


def reminder_for(payload: JsonObject, options: Options) -> str | None:
    rules = rules_at(RULES_PATH, options.harness.model_names)
    if hook_event_of(payload) in (HookEvent.SESSION_START, HookEvent.SUBAGENT_START):
        return session_start_reminder(rules, payload, options)
    if is_subagent(payload):
        return None
    return growth_reminder(rules, payload, options)


def parsed_options(argv: Sequence[str]) -> Options:
    parser = harness_parser()
    parser.add_argument("part", type=int, choices=range(1, REMINDER_PARTS + 1))
    arguments = parser.parse_args(argv)
    return Options(arguments.part, arguments.harness)


def main() -> None:
    options = parsed_options(sys.argv[1:])
    payload = read_payload()
    event = event_name_of(payload)
    if not event:
        return
    reminder = reminder_for(payload, options)
    if reminder:
        write_context(event, reminder, options.harness.output_shape)


if __name__ == "__main__":
    run_hook(main)
