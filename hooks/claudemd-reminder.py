#!/usr/bin/env python3

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


def transcript_tail(transcript_path):
    try:
        with open(transcript_path, "rb") as transcript:
            transcript.seek(0, os.SEEK_END)
            start = max(0, transcript.tell() - TRANSCRIPT_TAIL_BYTES)
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


def context_tokens(transcript_path):
    for line in reversed(transcript_tail(transcript_path)):
        usage = main_loop_usage(line)
        if not usage:
            continue
        return (
            usage.get("input_tokens", 0)
            + usage.get("cache_read_input_tokens", 0)
            + usage.get("cache_creation_input_tokens", 0)
        )
    return None


def mark_path(session_id):
    return os.path.join(MARK_DIR, re.sub(r"[^A-Za-z0-9_-]", "", session_id))


def read_mark(session_id):
    try:
        with open(mark_path(session_id), encoding="utf-8") as mark:
            return int(mark.read())
    except (OSError, ValueError):
        return None


def write_mark(session_id, tokens):
    os.makedirs(MARK_DIR, exist_ok=True)
    with open(mark_path(session_id), "w", encoding="utf-8") as mark:
        mark.write(str(tokens))


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
    session_id = payload.get("session_id")
    transcript_path = payload.get("transcript_path")
    if not (event and session_id and transcript_path):
        return
    if event == "SessionStart":
        emit(event, POINTER_REMINDER)
        return

    tokens = context_tokens(transcript_path)
    if tokens is None:
        if event == "UserPromptSubmit":
            emit(event, POINTER_REMINDER)
        return

    mark = read_mark(session_id)
    if mark is None or tokens < mark:
        write_mark(session_id, tokens)
        return
    if tokens - mark < REMINDER_INTERVAL_TOKENS:
        return

    claude_md = read_claude_md()
    if not claude_md:
        return
    write_mark(session_id, tokens)
    emit(event, f"{FULL_COPY_PREAMBLE}\n\n{claude_md}")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        sys.exit(0)
