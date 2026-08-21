#!/usr/bin/env python3

import fcntl
import json
import os
import re
import sys
import time

INTERVAL_TOKENS = 50_000
TAIL_BYTES = 1 << 20
BASELINE_LIFETIME_SECONDS = 7 * 24 * 60 * 60
CLAUDE_MD_PATH = os.path.expanduser("~/.claude/CLAUDE.md")
BASELINE_DIR = os.path.expanduser("~/.claude/claudemd-reminder")
CONTEXT_FIELDS = (
    "input_tokens",
    "cache_read_input_tokens",
    "cache_creation_input_tokens",
)
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


def sum_context_tokens(line):
    try:
        turn = json.loads(line)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    message = turn.get("message") or {}
    if turn.get("type") != "assistant" or turn.get("isSidechain"):
        return None
    if message.get("model") == "<synthetic>":
        return None
    usage = message.get("usage") or {}
    return sum(usage.get(field, 0) for field in CONTEXT_FIELDS) or None


def latest_context_tokens(transcript_path):
    try:
        with open(transcript_path, "rb") as transcript:
            transcript.seek(0, os.SEEK_END)
            start = max(0, transcript.tell() - TAIL_BYTES)
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
        return os.path.getsize(transcript_path) <= TAIL_BYTES
    except OSError:
        return True


def baseline_path(session_id):
    return os.path.join(BASELINE_DIR, re.sub(r"[^A-Za-z0-9_-]", "-", session_id))


def forget_baselines_of_dead_sessions():
    cutoff = time.time() - BASELINE_LIFETIME_SECONDS
    for name in os.listdir(BASELINE_DIR):
        baseline = os.path.join(BASELINE_DIR, name)
        try:
            if os.path.getmtime(baseline) < cutoff:
                os.unlink(baseline)
        except OSError:
            continue


def read_baseline(baseline_file):
    baseline_file.seek(0)
    try:
        return int(baseline_file.read())
    except ValueError:
        return None


def write_baseline(baseline_file, tokens):
    baseline_file.seek(0)
    baseline_file.truncate()
    baseline_file.write(str(tokens))


def advance_baseline(session_id, tokens):
    os.makedirs(BASELINE_DIR, exist_ok=True)
    path = baseline_path(session_id)
    if not os.path.exists(path):
        forget_baselines_of_dead_sessions()
    with open(path, "a+", encoding="utf-8") as baseline_file:
        fcntl.flock(baseline_file, fcntl.LOCK_EX)
        baseline = read_baseline(baseline_file)
        if baseline is None or tokens < baseline:
            write_baseline(baseline_file, tokens)
            return False
        if tokens - baseline < INTERVAL_TOKENS:
            return False
        write_baseline(baseline_file, tokens)
        return True


def emit(event, reminder):
    json.dump(
        {"hookSpecificOutput": {"hookEventName": event, "additionalContext": reminder}},
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

    tokens = latest_context_tokens(transcript_path)
    if tokens is None:
        if event == "UserPromptSubmit" and transcript_fits_in_tail(transcript_path):
            emit(event, POINTER_REMINDER)
        return
    if not advance_baseline(session_id, tokens):
        return

    with open(CLAUDE_MD_PATH, encoding="utf-8") as claude_md:
        emit(event, f"{FULL_COPY_PREAMBLE}\n\n{claude_md.read().strip()}")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        sys.exit(0)
