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
SPLIT_NOTICE = " The file comes in {total} parts, starting here."
LATER_PART_PREAMBLE = (
    "CLAUDE.md continues here, part {number} of {total}. It overrides your "
    "defaults. Follow it at all times."
)
BLOCK_BREAKS = (r"(?=\n\n# )", r"(?=\n\n)", r"(?=\n)")

Baselines = collections.namedtuple("Baselines", "pointed_at copied_at unsent")


def preamble_for(number, total):
    if number > 1:
        return LATER_PART_PREAMBLE.format(number=number, total=total)
    if total > 1:
        return FIRST_PART_PREAMBLE + SPLIT_NOTICE.format(total=total)
    return FIRST_PART_PREAMBLE


LONGEST_PREAMBLE_CHARS = max(len(preamble_for(number, 99)) for number in (1, 99))
PART_BUDGET_CHARS = MAX_INJECTED_CHARS - LONGEST_PREAMBLE_CHARS - len("\n\n")


def is_conversation_turn(entry):
    message = entry.get("message") or {}
    return (
        entry.get("type") == "assistant"
        and not entry.get("isSidechain")
        and message.get("model") != "<synthetic>"
    )


def context_tokens(line):
    try:
        entry = json.loads(line)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not is_conversation_turn(entry):
        return None
    usage = (entry.get("message") or {}).get("usage") or {}
    return sum(usage.get(field, 0) for field in CONTEXT_USAGE_FIELDS) or None


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
    with open(CLAUDE_MD_PATH, encoding="utf-8", errors="replace") as claude_md:
        text = claude_md.read().strip()
    if not text:
        return ()
    parts = parts_of(text, PART_BUDGET_CHARS)
    return tuple(
        f"{preamble_for(number, len(parts))}\n\n{part}"
        for number, part in enumerate(parts, start=1)
    )


def start_copy(tokens):
    messages = full_copy()
    if not messages:
        return None, Baselines(tokens, tokens, ())
    return messages[0], Baselines(tokens, tokens, messages[1:])


def send_next_part(baselines, tokens):
    sending, unsent = baselines.unsent[0], baselines.unsent[1:]
    if unsent:
        return sending, baselines._replace(unsent=unsent)
    return sending, Baselines(tokens, tokens, ())


def context_shrank(baselines, tokens):
    return tokens < baselines.pointed_at


def next_reminder(baselines, tokens):
    if baselines is None:
        return None, Baselines(tokens, tokens, ())
    if context_shrank(baselines, tokens):
        if baselines.unsent:
            return start_copy(tokens)
        return None, Baselines(tokens, tokens, ())
    if baselines.unsent:
        return send_next_part(baselines, tokens)
    if tokens - baselines.copied_at >= FULL_COPY_EVERY_TOKENS:
        return start_copy(tokens)
    if tokens - baselines.pointed_at >= POINTER_EVERY_TOKENS:
        return POINTER_REMINDER, baselines._replace(pointed_at=tokens)
    return None, baselines


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
    unsent = stored.get("unsent") or []
    if not isinstance(pointed_at, int) or not isinstance(copied_at, int):
        return None
    if not isinstance(unsent, list):
        return None
    if not all(isinstance(part, str) for part in unsent):
        return None
    return Baselines(pointed_at, copied_at, tuple(unsent))


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


def advance_baselines(session_id, tokens):
    with locked_baseline(session_id) as baseline_file:
        stored = read_baselines(baseline_file)
        reminder, baselines = next_reminder(stored, tokens)
        write_baselines(baseline_file, baselines)
        return reminder


def reminder_for(event, payload):
    if payload.get("agent_id") or not os.path.exists(CLAUDE_MD_PATH):
        return None
    if event == "SessionStart":
        return POINTER_REMINDER
    session_id = payload.get("session_id")
    transcript_path = payload.get("transcript_path")
    if not (session_id and transcript_path):
        return None
    tokens = latest_context_tokens(transcript_path)
    if tokens is not None:
        return advance_baselines(session_id, tokens)
    if event == "UserPromptSubmit" and transcript_fits_in_tail(transcript_path):
        return POINTER_REMINDER
    return None


def inject(event, reminder):
    json.dump(
        {"hookSpecificOutput": {"hookEventName": event, "additionalContext": reminder}},
        sys.stdout,
    )


def main():
    payload = json.loads(sys.stdin.read() or "{}")
    event = payload.get("hook_event_name")
    if not event:
        return
    reminder = reminder_for(event, payload)
    if reminder:
        inject(event, reminder)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        sys.exit(0)
