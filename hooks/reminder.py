#!/usr/bin/env python3

import fcntl
import json
import os
import re
import sys
import time

INTERVAL_TOKENS = 50_000
TAIL_BYTES = 1 << 20
MARK_LIFETIME_SECONDS = 7 * 24 * 60 * 60
CLAUDE_MD_PATH = os.path.expanduser("~/.claude/CLAUDE.md")
MARK_DIR = os.path.expanduser("~/.claude/claudemd-reminder")
SYNTHETIC_MODEL = "<synthetic>"
POINTER_REMINDER = (
    "CLAUDE.md holds the standing rules for this session and overrides your "
    f"defaults. Read {CLAUDE_MD_PATH} if it is not in your context, then "
    "follow it."
)
FULL_COPY_PREAMBLE = (
    "Your CLAUDE.md in full, repeated because the conversation has grown by "
    f"{INTERVAL_TOKENS // 1000}k tokens. It overrides your defaults. Read it "
    "and correct whatever you have drifted from."
)


def turn_tokens(line):
    try:
        turn = json.loads(line)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    message = turn.get("message") or {}
    if turn.get("type") != "assistant" or turn.get("isSidechain"):
        return None
    if message.get("model") == SYNTHETIC_MODEL:
        return None
    usage = message.get("usage") or {}
    return (
        usage.get("input_tokens", 0)
        + usage.get("cache_read_input_tokens", 0)
        + usage.get("cache_creation_input_tokens", 0)
    ) or None


def context_tokens(transcript_path):
    try:
        with open(transcript_path, "rb") as transcript:
            transcript.seek(0, os.SEEK_END)
            start = max(0, transcript.tell() - TAIL_BYTES)
            transcript.seek(start)
            lines = transcript.read().split(b"\n")[1 if start else 0 :]
    except OSError:
        return None
    for line in reversed(lines):
        tokens = turn_tokens(line)
        if tokens:
            return tokens
    return None


def reaches_beyond_tail(transcript_path):
    try:
        return os.path.getsize(transcript_path) > TAIL_BYTES
    except OSError:
        return False


def forget_stale_marks():
    cutoff = time.time() - MARK_LIFETIME_SECONDS
    for name in os.listdir(MARK_DIR):
        mark = os.path.join(MARK_DIR, name)
        try:
            if os.path.getmtime(mark) < cutoff:
                os.unlink(mark)
        except OSError:
            continue


def claim_full_copy(session_id, tokens):
    os.makedirs(MARK_DIR, exist_ok=True)
    path = os.path.join(MARK_DIR, re.sub(r"[^A-Za-z0-9_-]", "", session_id))
    with open(path, "a+", encoding="utf-8") as mark:
        fcntl.flock(mark, fcntl.LOCK_EX)
        mark.seek(0)
        try:
            baseline = int(mark.read())
        except ValueError:
            baseline = None
            forget_stale_marks()
        due = baseline is not None and tokens - baseline >= INTERVAL_TOKENS
        if due or baseline is None or tokens < baseline:
            mark.seek(0)
            mark.truncate()
            mark.write(str(tokens))
        return due


def emit(event, context):
    json.dump(
        {"hookSpecificOutput": {"hookEventName": event, "additionalContext": context}},
        sys.stdout,
    )


def main():
    payload = json.loads(sys.stdin.read() or "{}")
    event = payload.get("hook_event_name")
    if not event or payload.get("agent_id") or not os.path.exists(CLAUDE_MD_PATH):
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
        if event == "UserPromptSubmit" and not reaches_beyond_tail(transcript_path):
            emit(event, POINTER_REMINDER)
        return
    if not claim_full_copy(session_id, tokens):
        return

    with open(CLAUDE_MD_PATH, encoding="utf-8") as claude_md:
        emit(event, f"{FULL_COPY_PREAMBLE}\n\n{claude_md.read().strip()}")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        sys.exit(0)
