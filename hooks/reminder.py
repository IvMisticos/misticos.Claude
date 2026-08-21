#!/usr/bin/env python3

import enum
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
FULL_COPY_PREAMBLE = (
    "The conversation has grown since you last saw CLAUDE.md, so the file "
    "follows here in full. It overrides your defaults. Follow it at all "
    "times. Where your recent work has drifted from it, correct that now."
)


class Due(enum.Enum):
    NOTHING = enum.auto()
    POINTER = enum.auto()
    FULL_COPY = enum.auto()


def is_conversation_turn(entry):
    message = entry.get("message") or {}
    return (
        entry.get("type") == "assistant"
        and not entry.get("isSidechain")
        and message.get("model") != "<synthetic>"
    )


def sum_context_tokens(line):
    try:
        entry = json.loads(line)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not is_conversation_turn(entry):
        return None
    usage = (entry.get("message") or {}).get("usage") or {}
    return sum(usage.get(field, 0) for field in CONTEXT_USAGE_FIELDS) or None


def context_tokens_from_tail(transcript_path):
    try:
        with open(transcript_path, "rb") as transcript:
            transcript.seek(0, os.SEEK_END)
            start = max(0, transcript.tell() - TRANSCRIPT_TAIL_BYTES)
            transcript.seek(start)
            lines = transcript.read().split(b"\n")
    except OSError:
        return None
    if start:
        lines.pop(0)
    for line in reversed(lines):
        tokens = sum_context_tokens(line)
        if tokens:
            return tokens
    return None


def transcript_fits_in_tail(transcript_path):
    try:
        return os.path.getsize(transcript_path) <= TRANSCRIPT_TAIL_BYTES
    except OSError:
        return True


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


def read_baselines(baseline_file):
    baseline_file.seek(0)
    try:
        baselines = json.loads(baseline_file.read())
    except json.JSONDecodeError:
        return None, None
    pointed_at = baselines.get("pointed_at")
    copied_at = baselines.get("copied_at")
    if pointed_at is None or copied_at is None:
        return None, None
    return pointed_at, copied_at


def write_baselines(baseline_file, pointed_at, copied_at):
    baseline_file.seek(0)
    baseline_file.truncate()
    json.dump({"pointed_at": pointed_at, "copied_at": copied_at}, baseline_file)


def advance_baselines(session_id, tokens):
    os.makedirs(BASELINE_DIR, exist_ok=True)
    path = baseline_path(session_id)
    if not os.path.exists(path):
        forget_baselines_of_dead_sessions()
    with open(path, "a+", encoding="utf-8") as baseline_file:
        fcntl.flock(baseline_file, fcntl.LOCK_EX)
        pointed_at, copied_at = read_baselines(baseline_file)
        if pointed_at is None or tokens < pointed_at:
            write_baselines(baseline_file, tokens, tokens)
            return Due.NOTHING
        if tokens - copied_at >= FULL_COPY_EVERY_TOKENS:
            write_baselines(baseline_file, tokens, tokens)
            return Due.FULL_COPY
        if tokens - pointed_at >= POINTER_EVERY_TOKENS:
            write_baselines(baseline_file, tokens, copied_at)
            return Due.POINTER
        return Due.NOTHING


def full_copy():
    with open(CLAUDE_MD_PATH, encoding="utf-8") as claude_md:
        return f"{FULL_COPY_PREAMBLE}\n\n{claude_md.read().strip()}"


def reminder_for(event, payload):
    if payload.get("agent_id") or not os.path.exists(CLAUDE_MD_PATH):
        return None
    if event == "SessionStart":
        return POINTER_REMINDER

    session_id = payload.get("session_id")
    transcript_path = payload.get("transcript_path")
    if not (session_id and transcript_path):
        return None

    tokens = context_tokens_from_tail(transcript_path)
    if tokens is None:
        if event == "UserPromptSubmit" and transcript_fits_in_tail(transcript_path):
            return POINTER_REMINDER
        return None
    due = advance_baselines(session_id, tokens)
    if due is Due.FULL_COPY:
        return full_copy()
    if due is Due.POINTER:
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
