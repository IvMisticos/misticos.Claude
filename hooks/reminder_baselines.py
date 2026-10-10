import collections
import contextlib
import json
import os
import re
import sys
import time

if sys.platform == "win32":
    import msvcrt
else:
    import fcntl

FULL_COPY_EVERY_TOKENS = 100_000
POINTER_EVERY_TOKENS = 25_000
FORGET_BASELINE_AFTER_SECONDS = 7 * 24 * 60 * 60
BASELINE_DIR = os.path.expanduser("~/.claude/hooks/data/misticos.Claude/reminder")
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


def baseline_path(session_id):
    return os.path.join(BASELINE_DIR, re.sub(r"[^A-Za-z0-9_-]", "-", session_id))


def forget_baselines_of_dead_sessions():
    cutoff = time.time() - FORGET_BASELINE_AFTER_SECONDS
    for name in os.listdir(BASELINE_DIR):
        baseline = os.path.join(BASELINE_DIR, name)
        try:
            if os.path.getmtime(baseline) < cutoff:
                os.unlink(baseline)
        except OSError:
            continue


@contextlib.contextmanager
def locked_baseline(session_id):
    os.makedirs(BASELINE_DIR, exist_ok=True)
    path = baseline_path(session_id)
    if not os.path.exists(path):
        forget_baselines_of_dead_sessions()
    with open(path, "a+", encoding="utf-8") as baseline_file:
        lock_exclusively(baseline_file)
        yield baseline_file


def lock_exclusively(baseline_file):
    if sys.platform != "win32":
        fcntl.flock(baseline_file, fcntl.LOCK_EX)
        return
    baseline_file.seek(0)
    with contextlib.suppress(OSError):
        msvcrt.locking(baseline_file.fileno(), msvcrt.LK_LOCK, 1)


def parsed_baselines(stored):
    if not isinstance(stored, dict):
        return None
    pointed_at = stored.get("pointed_at")
    copied_at = stored.get("copied_at")
    fire = stored.get("fire") or ""
    action = stored.get("action") or IDLE
    seen = stored.get("seen") or 0
    if not all(isinstance(count, int) for count in (pointed_at, copied_at, seen)):
        return None
    if not isinstance(fire, str) or action not in (IDLE, POINTER, COPY):
        return None
    return Baselines(pointed_at, copied_at, fire, action, seen)


def read_baselines(baseline_file):
    baseline_file.seek(0)
    try:
        return parsed_baselines(json.loads(baseline_file.read()))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None


def write_baselines(baseline_file, baselines):
    baseline_file.seek(0)
    baseline_file.truncate()
    json.dump(baselines._asdict(), baseline_file)


def claim_action(session_id, fire, can_copy, tokens=None, added_tokens=0):
    with locked_baseline(session_id) as baseline_file:
        stored = read_baselines(baseline_file)
        if tokens is None:
            already_this_fire = stored is not None and fire and stored.fire == fire
            seen = stored.seen if stored else 0
            tokens = seen if already_this_fire else seen + added_tokens
        action, baselines = action_for_fire(stored, fire, tokens, can_copy)
        write_baselines(baseline_file, baselines._replace(seen=tokens))
        return action


def forget_baseline(session_id):
    with contextlib.suppress(OSError):
        os.unlink(baseline_path(session_id))
