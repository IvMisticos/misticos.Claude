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
    rules_text,
)
from rules_receipts import (
    confirm_session_start_copy,
    has_received,
    note_received,
    note_sent_at_session_start,
    rules_digest,
)
from transcript import context_tokens, payload_tokens

from agents import ALL_SECTIONS, rule_sections_for

RULES_PATH = str(PLUGIN_ROOT / "INSTRUCTIONS.md")
REMINDER_PARTS = 4


class Options(NamedTuple):
    part: int
    harness: Harness


def message_for_part(
    action: Action, part: int, messages: Sequence[str], rules: Rules
) -> str | None:
    match action:
        case Action.POINTER:
            return pointer_reminder(rules) if part == 1 else None
        case Action.COPY:
            return messages[part - 1] if part <= len(messages) else None
        case Action.IDLE:
            return None


def main_session_digest(rules: Rules) -> str:
    return rules_digest(rules_text(rules))


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


def growth_reminder(
    rules: Rules, event: HookEvent, payload: JsonObject, options: Options
) -> str | None:
    messages = full_copy_messages(rules, GROWN_PREAMBLE)
    session_id = session_id_of(payload)
    if not (messages and session_id):
        return None
    if options.part == 1:
        confirm_session_start_copy(session_id)
    fire = fire_id(event, payload)
    if not fire and options.part > 1:
        return None
    context = measured_context(payload, options.harness.context_from)
    if context is None:
        return None
    action = claim_action(
        session_id,
        fire,
        context,
        can_copy=len(messages) <= REMINDER_PARTS and bool(fire or len(messages) == 1),
        can_point=event != HookEvent.USER_PROMPT_SUBMIT,
    )
    if action == Action.COPY:
        note_received(session_id, main_session_digest(rules))
    return message_for_part(action, options.part, messages, rules)


def session_start_reminder(
    rules: Rules, event: HookEvent, payload: JsonObject, options: Options
) -> str | None:
    for_subagent = is_subagent(payload) or event == HookEvent.SUBAGENT_START
    session_id = session_id_of(payload)
    if options.part == 1 and session_id and not for_subagent:
        forget_baseline(session_id)
        note_sent_at_session_start(session_id, main_session_digest(rules))
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
    return message_for_part(Action.COPY, options.part, messages, rules)


def resumes_with_same_rules(
    rules: Rules, event: HookEvent, payload: JsonObject
) -> bool:
    session_id = session_id_of(payload)
    return (
        event == HookEvent.SESSION_START
        and not is_subagent(payload)
        and payload.get("source") == "resume"
        and session_id is not None
        and has_received(session_id, main_session_digest(rules))
    )


def reminder_for(event: HookEvent, payload: JsonObject, options: Options) -> str | None:
    rules = rules_at(RULES_PATH, options.harness.model_names)
    if resumes_with_same_rules(rules, event, payload):
        return None
    if event in (HookEvent.SESSION_START, HookEvent.SUBAGENT_START):
        return session_start_reminder(rules, event, payload, options)
    if is_subagent(payload):
        return None
    return growth_reminder(rules, event, payload, options)


def parsed_options(argv: Sequence[str]) -> Options:
    parser = harness_parser()
    parser.add_argument("part", type=int, choices=range(1, REMINDER_PARTS + 1))
    arguments = parser.parse_args(argv)
    return Options(arguments.part, arguments.harness)


def main() -> None:
    options = parsed_options(sys.argv[1:])
    payload = read_payload()
    event = hook_event_of(payload)
    if event is None:
        return
    reminder = reminder_for(event, payload, options)
    if reminder:
        write_context(event_name_of(payload), reminder, options.harness.output_shape)


if __name__ == "__main__":
    run_hook(main)
