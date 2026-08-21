#!/usr/bin/env python3

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
PREAMBLE_RESERVE_CHARS = 400
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
SPLIT_NOTICE = " The file is split across {total} messages, starting here."
LATER_PART_PREAMBLE = "CLAUDE.md continues here, part {number} of {total}."
SPLIT_PREFERENCES = ("\n\n# ", "\n\n", "\n")


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


def split_once(text, budget):
    window = text[:budget]
    boundaries = [window.rfind(preference) for preference in SPLIT_PREFERENCES]
    filling = [at for at in boundaries if at >= budget // 2]
    if not filling:
        return text[:budget], text[budget:]
    return text[:filling[0]], text[filling[0] :].lstrip("\n")


def claude_md_parts():
    with open(CLAUDE_MD_PATH, encoding="utf-8") as claude_md:
        text = claude_md.read().strip()
    budget = MAX_INJECTED_CHARS - PREAMBLE_RESERVE_CHARS
    parts = []
    while len(text) > budget:
        part, text = split_once(text, budget)
        parts.append(part)
    if text:
        parts.append(text)
    return parts


def part_message(index, parts):
    if index:
        preamble = LATER_PART_PREAMBLE.format(number=index + 1, total=len(parts))
    elif len(parts) > 1:
        preamble = FULL_COPY_PREAMBLE + SPLIT_NOTICE.format(total=len(parts))
    else:
        preamble = FULL_COPY_PREAMBLE
    return f"{preamble}\n\n{parts[index]}"


def full_copy_messages():
    parts = claude_md_parts()
    return [part_message(index, parts) for index in range(len(parts))]


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


def read_state(baseline_file):
    baseline_file.seek(0)
    try:
        state = json.loads(baseline_file.read())
    except json.JSONDecodeError:
        return None
    if state.get("pointed_at") is None or state.get("copied_at") is None:
        return None
    return state


def write_state(baseline_file, pointed_at, copied_at, pending):
    baseline_file.seek(0)
    baseline_file.truncate()
    json.dump(
        {"pointed_at": pointed_at, "copied_at": copied_at, "pending": pending},
        baseline_file,
    )


def start_full_copy(baseline_file, tokens):
    messages = full_copy_messages()
    write_state(baseline_file, tokens, tokens, messages[1:])
    return messages[0] if messages else None


def due_reminder(session_id, tokens):
    os.makedirs(BASELINE_DIR, exist_ok=True)
    path = baseline_path(session_id)
    if not os.path.exists(path):
        forget_baselines_of_dead_sessions()
    with open(path, "a+", encoding="utf-8") as baseline_file:
        fcntl.flock(baseline_file, fcntl.LOCK_EX)
        state = read_state(baseline_file)
        if state is None or tokens < state["pointed_at"]:
            if state and state.get("pending"):
                return start_full_copy(baseline_file, tokens)
            write_state(baseline_file, tokens, tokens, [])
            return None
        pending = state.get("pending") or []
        if pending:
            if len(pending) > 1:
                write_state(
                    baseline_file,
                    state["pointed_at"],
                    state["copied_at"],
                    pending[1:],
                )
            else:
                write_state(baseline_file, tokens, tokens, [])
            return pending[0]
        if tokens - state["copied_at"] >= FULL_COPY_EVERY_TOKENS:
            return start_full_copy(baseline_file, tokens)
        if tokens - state["pointed_at"] >= POINTER_EVERY_TOKENS:
            write_state(baseline_file, tokens, state["copied_at"], [])
            return POINTER_REMINDER
        return None


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
    return due_reminder(session_id, tokens)


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
