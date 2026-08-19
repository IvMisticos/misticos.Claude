#!/usr/bin/env python3

import fcntl
import json
import os
import re
import sys

REMINDER_INTERVAL_TOKENS = 50_000
TRANSCRIPT_TAIL_BYTES = 1 << 20
CLAUDE_MD_PATH = os.path.expanduser("~/.claude/CLAUDE.md")
MARK_DIR = os.path.expanduser("~/.claude/claudemd-reminder")
FULL_COPY_PREAMBLE = (
    "Your CLAUDE.md in full, repeated because the conversation has grown by "
    f"{REMINDER_INTERVAL_TOKENS // 1000}k tokens. It overrides your defaults. "
    "Read it and correct whatever you have drifted from."
)
POINTER_REMINDER = (
    "CLAUDE.md holds the standing rules for this session and overrides your "
    f"defaults. Read {CLAUDE_MD_PATH} if it is not in your context, then "
    "follow it."
)


def transcript_lines(transcript_path, tail_bytes):
    try:
        with open(transcript_path, "rb") as transcript:
            start = 0
            if tail_bytes is not None:
                transcript.seek(0, os.SEEK_END)
                start = max(0, transcript.tell() - tail_bytes)
                transcript.seek(start)
            lines = transcript.read().split(b"\n")
    except OSError:
        return []
    return lines[1:] if start else lines


def main_loop_usage(line):
    try:
        entry = json.loads(line)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if entry.get("type") != "assistant" or entry.get("isSidechain"):
        return None
    return (entry.get("message") or {}).get("usage")


def latest_usage(lines):
    for line in reversed(lines):
        usage = main_loop_usage(line)
        if usage:
            return usage
    return None


def context_tokens(transcript_path):
    for tail_bytes in (TRANSCRIPT_TAIL_BYTES, None):
        usage = latest_usage(transcript_lines(transcript_path, tail_bytes))
        if usage:
            return (
                usage.get("input_tokens", 0)
                + usage.get("cache_read_input_tokens", 0)
                + usage.get("cache_creation_input_tokens", 0)
            )
    return None


def mark_path(session_id):
    return os.path.join(MARK_DIR, re.sub(r"[^A-Za-z0-9_-]", "", session_id))


def read_baseline(mark):
    mark.seek(0)
    try:
        return int(mark.read())
    except ValueError:
        return None


def write_baseline(mark, tokens):
    mark.seek(0)
    mark.truncate()
    mark.write(str(tokens))


def claim_full_copy(session_id, tokens):
    os.makedirs(MARK_DIR, exist_ok=True)
    with open(mark_path(session_id), "a+", encoding="utf-8") as mark:
        fcntl.flock(mark, fcntl.LOCK_EX)
        baseline = read_baseline(mark)
        due = baseline is not None and tokens - baseline >= REMINDER_INTERVAL_TOKENS
        if due or baseline is None or tokens < baseline:
            write_baseline(mark, tokens)
        return due


def read_claude_md():
    try:
        with open(CLAUDE_MD_PATH, encoding="utf-8") as claude_md:
            return claude_md.read().strip()
    except OSError:
        return None


def emit(event, context):
    json.dump(
        {"hookSpecificOutput": {"hookEventName": event, "additionalContext": context}},
        sys.stdout,
    )


def main():
    payload = json.loads(sys.stdin.read() or "{}")
    event = payload.get("hook_event_name")
    if not event:
        return
    if event == "SessionStart":
        emit(event, POINTER_REMINDER)
        return

    session_id = payload.get("session_id")
    transcript_path = payload.get("transcript_path")
    if not (session_id and transcript_path):
        return

    tokens = context_tokens(transcript_path)
    if tokens is None:
        if event == "UserPromptSubmit":
            emit(event, POINTER_REMINDER)
        return
    claude_md = read_claude_md()
    if not claude_md:
        return
    if claim_full_copy(session_id, tokens):
        emit(event, f"{FULL_COPY_PREAMBLE}\n\n{claude_md}")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        sys.exit(0)
