#!/usr/bin/env python3

import collections
import contextlib
import fcntl
import json
import os
import re
import sys
import time

FULL_COPY_EVERY_TOKENS = 50_000
POINTER_EVERY_TOKENS = 10_000
TRANSCRIPT_TAIL_BYTES = 1 << 20
FORGET_BASELINE_AFTER_SECONDS = 7 * 24 * 60 * 60
MAX_INJECTED_CHARS = 10_000
CLAUDE_MD_PATH = os.path.expanduser("~/.claude/CLAUDE.md")
BASELINE_DIR = os.path.expanduser("~/.claude/hooks/data/misticos.Claude/reminder")
CONTEXT_USAGE_FIELDS = (
    "input_tokens",
    "cache_read_input_tokens",
    "cache_creation_input_tokens",
)
POINTER_REMINDER = (
    "CLAUDE.md holds the standing rules for this session and overrides your "
    "defaults. Follow it at all times. If you notice you have drifted from "
    f"it, read {CLAUDE_MD_PATH} to bring it back into your context."
)
FIRST_PART_PREAMBLE = (
    "The conversation has grown since you last saw CLAUDE.md, so the file "
    "follows here in full. It overrides your defaults. Follow it at all "
    "times. Where your recent work has drifted from it, correct that now."
)
SPLIT_NOTICE = " The file comes in {total} parts, sent together, in any order."
LATER_PART_PREAMBLE = (
    "CLAUDE.md continues here, part {number} of {total}. It overrides your "
    "defaults. Follow it at all times."
)
BLOCK_BREAKS = (r"(?=\n\n# )", r"(?=\n\n)", r"(?=\n)")
OUTGROWN_NOTICE = (
    "CLAUDE.md now needs {parts} hook entries and {entries} are installed, so "
    "the whole file can no longer be sent. Re-run setup.sh."
)
IDLE = ""
POINTER = "pointer"
COPY = "copy"

Baselines = collections.namedtuple("Baselines", "pointed_at copied_at fire action")
Reminder = collections.namedtuple("Reminder", "context notice")

SILENCE = Reminder(None, None)
POINTER_ONLY = Reminder(POINTER_REMINDER, None)


def preamble_for(number, total):
    if number > 1:
        return LATER_PART_PREAMBLE.format(number=number, total=total)
    if total > 1:
        return FIRST_PART_PREAMBLE + SPLIT_NOTICE.format(total=total)
    return FIRST_PART_PREAMBLE


LONGEST_PREAMBLE_CHARS = max(len(preamble_for(number, 99)) for number in (1, 99))
PART_BUDGET_CHARS = MAX_INJECTED_CHARS - LONGEST_PREAMBLE_CHARS - len("\n\n")


def as_dict(value):
    return value if isinstance(value, dict) else {}


def is_conversation_turn(entry):
    return (
        entry.get("type") == "assistant"
        and not entry.get("isSidechain")
        and as_dict(entry.get("message")).get("model") != "<synthetic>"
    )


def counted_tokens(usage):
    counts = (as_dict(usage).get(field) for field in CONTEXT_USAGE_FIELDS)
    return sum(count for count in counts if isinstance(count, int))


def context_tokens(line):
    try:
        entry = json.loads(line)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(entry, dict) or not is_conversation_turn(entry):
        return None
    return counted_tokens(as_dict(entry.get("message")).get("usage")) or None


def transcript_tail(transcript_path):
    with open(transcript_path, "rb") as transcript:
        transcript.seek(0, os.SEEK_END)
        start = max(0, transcript.tell() - TRANSCRIPT_TAIL_BYTES)
        transcript.seek(start)
        lines = transcript.read().split(b"\n")
    return lines if start == 0 else lines[1:]


def latest_context_tokens(transcript_path):
    try:
        lines = transcript_tail(transcript_path)
    except OSError:
        return None
    for line in reversed(lines):
        tokens = context_tokens(line)
        if tokens:
            return tokens
    return None


def transcript_fits_in_tail(transcript_path):
    try:
        return os.path.getsize(transcript_path) <= TRANSCRIPT_TAIL_BYTES
    except OSError:
        return True


def packed(blocks, budget):
    parts = []
    for block in blocks:
        if parts and len(parts[-1]) + len(block) <= budget:
            parts[-1] += block
        else:
            parts.append(block.lstrip("\n"))
    return parts


def cut_every(text, budget):
    return [text[at : at + budget] for at in range(0, len(text), budget)]


def parts_of(text, budget):
    for block_break in BLOCK_BREAKS:
        parts = packed(re.split(block_break, text), budget)
        if all(len(part) <= budget for part in parts):
            return parts
    return cut_every(text, budget)


def full_copy():
    try:
        with open(CLAUDE_MD_PATH, encoding="utf-8", errors="replace") as claude_md:
            text = claude_md.read().strip()
    except OSError:
        return ()
    if not text:
        return ()
    parts = parts_of(text, PART_BUDGET_CHARS)
    return tuple(
        f"{preamble_for(number, len(parts))}\n\n{part}"
        for number, part in enumerate(parts, start=1)
    )


def hook_entries_needed():
    return max(1, len(full_copy()))


def fire_id(event, payload):
    calls = payload.get("tool_calls") or []
    tool_uses = sorted(
        str(call.get("tool_use_id"))
        for call in calls
        if isinstance(call, dict) and call.get("tool_use_id")
    )
    prompt = str(payload.get("prompt_id") or "")
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
        fcntl.flock(baseline_file, fcntl.LOCK_EX)
        yield baseline_file


def as_baselines(stored):
    if not isinstance(stored, dict):
        return None
    pointed_at = stored.get("pointed_at")
    copied_at = stored.get("copied_at")
    fire = stored.get("fire") or ""
    action = stored.get("action") or IDLE
    if not isinstance(pointed_at, int) or not isinstance(copied_at, int):
        return None
    if not isinstance(fire, str) or action not in (IDLE, POINTER, COPY):
        return None
    return Baselines(pointed_at, copied_at, fire, action)


def read_baselines(baseline_file):
    baseline_file.seek(0)
    try:
        return as_baselines(json.loads(baseline_file.read()))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None


def write_baselines(baseline_file, baselines):
    baseline_file.seek(0)
    baseline_file.truncate()
    json.dump(baselines._asdict(), baseline_file)


def claimed_action(session_id, fire, tokens, can_copy):
    with locked_baseline(session_id) as baseline_file:
        stored = read_baselines(baseline_file)
        action, baselines = action_for_fire(stored, fire, tokens, can_copy)
        write_baselines(baseline_file, baselines)
        return action


def pointer_for(part, parts, entries):
    if part != 1:
        return SILENCE
    if len(parts) <= entries:
        return POINTER_ONLY
    notice = OUTGROWN_NOTICE.format(parts=len(parts), entries=entries)
    return Reminder(POINTER_REMINDER, notice)


def message_for(action, part, parts, entries):
    if action == POINTER:
        return pointer_for(part, parts, entries)
    if action != COPY or not 1 <= part <= len(parts):
        return SILENCE
    return Reminder(parts[part - 1], None)


def reminder_for(event, payload, part, entries):
    parts = full_copy()
    if payload.get("agent_id") or not parts:
        return SILENCE
    if event == "SessionStart":
        return pointer_for(part, parts, entries)
    session_id = payload.get("session_id")
    transcript_path = payload.get("transcript_path")
    if not (session_id and transcript_path):
        return SILENCE
    tokens = latest_context_tokens(transcript_path)
    if tokens is None:
        if event == "UserPromptSubmit" and transcript_fits_in_tail(transcript_path):
            return pointer_for(part, parts, entries)
        return SILENCE
    fire = fire_id(event, payload)
    if not fire and part > 1:
        return SILENCE
    sendable = len(parts) <= entries and (fire or len(parts) == 1)
    action = claimed_action(session_id, fire, tokens, bool(sendable))
    return message_for(action, part, parts, entries)


def inject(event, reminder):
    output = {
        "hookSpecificOutput": {
            "hookEventName": event,
            "additionalContext": reminder.context,
        }
    }
    if reminder.notice:
        output["systemMessage"] = reminder.notice
    json.dump(output, sys.stdout)


def main():
    part = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    entries = int(sys.argv[2]) if len(sys.argv) > 2 else part
    payload = json.loads(sys.stdin.read() or "{}")
    event = payload.get("hook_event_name")
    if not event:
        return
    reminder = reminder_for(event, payload, part, entries)
    if reminder.context:
        inject(event, reminder)


if __name__ == "__main__":
    if sys.argv[1:2] == ["--entries"]:
        print(hook_entries_needed())
    else:
        try:
            main()
        except Exception:
            sys.exit(0)
