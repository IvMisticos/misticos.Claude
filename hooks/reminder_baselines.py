import collections
import contextlib
import os

from session_state import (
    STATE_ROOT,
    locked_session_file,
    parsed_record,
    read_json,
    session_file_path,
    write_json,
)

FULL_COPY_EVERY_TOKENS = 100_000
POINTER_EVERY_TOKENS = 25_000
BASELINE_DIR = os.path.join(STATE_ROOT, "reminder")
IDLE = ""
POINTER = "pointer"
COPY = "copy"
Baselines = collections.namedtuple(
    "Baselines", "pointed_at copied_at fire action seen", defaults=(0,)
)


def fire_id(event, payload):
    calls = payload.get("tool_calls") or []
    tool_uses = sorted(
        str(call.get("tool_use_id"))
        for call in calls
        if isinstance(call, dict) and call.get("tool_use_id")
    )
    if payload.get("tool_use_id"):
        tool_uses.append(str(payload["tool_use_id"]))
    prompt = str(
        payload.get("prompt_id")
        or payload.get("turn_id")
        or payload.get("generation_id")
        or ""
    )
    if not (prompt or tool_uses):
        return ""
    return "|".join([event, prompt] + tool_uses)


def context_shrank(baselines, tokens):
    return tokens < baselines.pointed_at


def next_action(baselines, fire, tokens, can_copy):
    if baselines is None or context_shrank(baselines, tokens):
        return IDLE, Baselines(tokens, tokens, fire, IDLE)
    if can_copy and tokens - baselines.copied_at >= FULL_COPY_EVERY_TOKENS:
        return COPY, Baselines(tokens, tokens, fire, COPY)
    if tokens - baselines.pointed_at >= POINTER_EVERY_TOKENS:
        return POINTER, Baselines(tokens, baselines.copied_at, fire, POINTER)
    return IDLE, baselines._replace(fire=fire, action=IDLE)


def action_for_fire(baselines, fire, tokens, can_copy):
    if baselines is not None and fire and baselines.fire == fire:
        return baselines.action, baselines
    return next_action(baselines, fire, tokens, can_copy)


def parsed_baselines(stored):
    baselines = parsed_record(Baselines, stored)
    if baselines is None:
        return None
    counts = (baselines.pointed_at, baselines.copied_at, baselines.seen)
    valid = (
        all(isinstance(count, int) for count in counts)
        and isinstance(baselines.fire, str)
        and baselines.action in (IDLE, POINTER, COPY)
    )
    return baselines if valid else None


def claim_action(session_id, fire, can_copy, tokens=None, added_tokens=0):
    with locked_session_file(BASELINE_DIR, session_id) as baseline_file:
        stored = parsed_baselines(read_json(baseline_file))
        if tokens is None:
            already_this_fire = stored is not None and fire and stored.fire == fire
            seen = stored.seen if stored else 0
            tokens = seen if already_this_fire else seen + added_tokens
        action, baselines = action_for_fire(stored, fire, tokens, can_copy)
        write_json(baseline_file, baselines._replace(seen=tokens)._asdict())
        return action


def forget_baseline(session_id):
    with contextlib.suppress(OSError):
        os.unlink(session_file_path(BASELINE_DIR, session_id))
