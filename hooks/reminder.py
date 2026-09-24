#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///

import argparse
import collections
import contextlib
import json
import os
import re
import sys
import time
import traceback

if sys.platform == "win32":
    import msvcrt
else:
    import fcntl

FULL_COPY_EVERY_TOKENS = 50_000
POINTER_EVERY_TOKENS = 10_000
TRANSCRIPT_TAIL_BYTES = 1 << 20
FORGET_BASELINE_AFTER_SECONDS = 7 * 24 * 60 * 60
MAX_INJECTED_CHARS = 10_000
CHARS_PER_TOKEN_ESTIMATE = 4
BASELINE_DIR = os.path.expanduser("~/.claude/hooks/data/misticos.Claude/reminder")
CONTEXT_USAGE_FIELDS = (
    "input_tokens",
    "cache_read_input_tokens",
    "cache_creation_input_tokens",
)
POINTER_REMINDER = (
    "{name} holds the standing rules for this session and overrides your "
    "defaults. Follow it at all times. Silence is the default: write to me "
    "only what changes what I do next, and keep subagent prompts as short as "
    "the work allows. If you notice you have drifted, read {path} to bring "
    "the rules back into your context."
)
MODEL_NAMES_NOTE = " In {name}, {meanings}."
GROWN_PREAMBLE = (
    "The conversation has grown since you last saw {name}, so the file "
    "follows here in full. It overrides your defaults. Follow it at all "
    "times. Where your recent work has drifted from it, correct that now."
)
SESSION_START_PREAMBLE = (
    "{name} holds the standing rules for this session and follows here in "
    "full. It overrides your defaults. Follow it at all times."
)
SPLIT_NOTICE = " The file comes in {total} parts, sent together, in any order."
LATER_PART_PREAMBLE = (
    "{name} continues here, part {number} of {total}. It overrides your "
    "defaults. Follow it at all times."
)
MODEL_TIER = re.compile(r"\bthe (fast|strong|lead) model\b", re.IGNORECASE)
BLOCK_BREAKS = (r"(?=\n\n# )", r"(?=\n\n)", r"(?=\n)")
IDLE = ""
POINTER = "pointer"
COPY = "copy"

Baselines = collections.namedtuple(
    "Baselines", "pointed_at copied_at fire action seen", defaults=(0,)
)
Rules = collections.namedtuple("Rules", "path name model_names")


def rules_at(path, model_names):
    expanded = os.path.expanduser(path)
    return Rules(expanded, os.path.basename(expanded), model_names)


def with_model_names(text, model_names):
    def named(match):
        return model_names.get(match[1].lower()) or match[0]

    return MODEL_TIER.sub(named, text)


def model_names_note(rules):
    meanings = [
        f"the {tier} model means {model_name}"
        for tier, model_name in rules.model_names.items()
        if model_name
    ]
    if not meanings:
        return ""
    return MODEL_NAMES_NOTE.format(name=rules.name, meanings=", ".join(meanings))


def pointer_reminder(rules):
    pointer = POINTER_REMINDER.format(name=rules.name, path=rules.path)
    return pointer + model_names_note(rules)


def preamble_for(number, total, name, first_preamble):
    if number > 1:
        return LATER_PART_PREAMBLE.format(name=name, number=number, total=total)
    if total > 1:
        return first_preamble.format(name=name) + SPLIT_NOTICE.format(total=total)
    return first_preamble.format(name=name)


def part_budget_chars(name, first_preamble):
    longest_preamble = max(
        len(preamble_for(number, 99, name, first_preamble)) for number in (1, 99)
    )
    return MAX_INJECTED_CHARS - longest_preamble - len("\n\n")


def dict_or_empty(value):
    return value if isinstance(value, dict) else {}


def is_conversation_turn(entry):
    return (
        entry.get("type") == "assistant"
        and not entry.get("isSidechain")
        and dict_or_empty(entry.get("message")).get("model") != "<synthetic>"
    )


def usage_context_tokens(usage):
    counts = (dict_or_empty(usage).get(field) for field in CONTEXT_USAGE_FIELDS)
    return sum(count for count in counts if isinstance(count, int))


def line_context_tokens(line):
    try:
        entry = json.loads(line)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(entry, dict) or not is_conversation_turn(entry):
        return None
    usage = dict_or_empty(entry.get("message")).get("usage")
    return usage_context_tokens(usage) or None


def transcript_tail_lines(transcript_path):
    with open(transcript_path, "rb") as transcript:
        transcript.seek(0, os.SEEK_END)
        start = max(0, transcript.tell() - TRANSCRIPT_TAIL_BYTES)
        transcript.seek(start)
        lines = transcript.read().split(b"\n")
    return lines if start == 0 else lines[1:]


def latest_context_tokens(transcript_path):
    try:
        lines = transcript_tail_lines(transcript_path)
    except OSError:
        return None
    for line in reversed(lines):
        tokens = line_context_tokens(line)
        if tokens:
            return tokens
    return None


def context_tokens_from_size(transcript_path):
    try:
        return os.path.getsize(transcript_path) // CHARS_PER_TOKEN_ESTIMATE or None
    except OSError:
        return None


def payload_tokens(payload):
    tool_text = json.dumps(payload.get("tool_input")) + str(
        payload.get("tool_output") or ""
    )
    return len(tool_text) // CHARS_PER_TOKEN_ESTIMATE


def transcript_fits_in_tail(transcript_path):
    try:
        return os.path.getsize(transcript_path) <= TRANSCRIPT_TAIL_BYTES
    except OSError:
        return True


def packed_parts(blocks, budget):
    parts = []
    for block in blocks:
        if parts and len(parts[-1]) + len(block) <= budget:
            parts[-1] += block
        else:
            parts.append(block.lstrip("\n"))
    return parts


def fixed_size_chunks(text, budget):
    return [text[at : at + budget] for at in range(0, len(text), budget)]


def parts_within_budget(text, budget):
    for block_break in BLOCK_BREAKS:
        parts = packed_parts(re.split(block_break, text), budget)
        if all(len(part) <= budget for part in parts):
            return parts
    return fixed_size_chunks(text, budget)


def part_messages(text, budget, name, first_preamble):
    parts = parts_within_budget(text, budget)
    return tuple(
        f"{preamble_for(number, len(parts), name, first_preamble)}\n\n{part}"
        for number, part in enumerate(parts, start=1)
    )


def full_copy_messages(rules, first_preamble):
    try:
        with open(rules.path, encoding="utf-8", errors="replace") as rules_file:
            text = with_model_names(rules_file.read().strip(), rules.model_names)
    except OSError as error:
        print(f"reminder: cannot read rules: {error}", file=sys.stderr)
        return ()
    if not text:
        return ()
    budget = part_budget_chars(rules.name, first_preamble)
    while True:
        messages = part_messages(text, budget, rules.name, first_preamble)
        overflow = max(len(message) for message in messages) - MAX_INJECTED_CHARS
        if overflow <= 0:
            return messages
        budget -= overflow


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


def claim_action(session_id, fire, tokens, can_copy):
    with locked_baseline(session_id) as baseline_file:
        stored = read_baselines(baseline_file)
        action, baselines = action_for_fire(stored, fire, tokens, can_copy)
        write_baselines(baseline_file, baselines._replace(seen=tokens))
        return action


def claim_action_by_payload(session_id, fire, added_tokens, can_copy):
    with locked_baseline(session_id) as baseline_file:
        stored = read_baselines(baseline_file)
        already_this_fire = stored is not None and fire and stored.fire == fire
        seen = stored.seen if stored else 0
        tokens = seen if already_this_fire else seen + added_tokens
        action, baselines = action_for_fire(stored, fire, tokens, can_copy)
        write_baselines(baseline_file, baselines._replace(seen=tokens))
        return action


def message_for_part(action, part, messages, rules):
    if action == POINTER:
        return pointer_reminder(rules) if part == 1 else None
    if action != COPY or not 1 <= part <= len(messages):
        return None
    return messages[part - 1]


def context_tokens(transcript_path, source):
    if source == "size":
        return context_tokens_from_size(transcript_path)
    return latest_context_tokens(transcript_path)


def growth_reminder(rules, payload, options):
    messages = full_copy_messages(rules, GROWN_PREAMBLE)
    session_id = payload.get("session_id") or payload.get("conversation_id")
    if not (messages and session_id):
        return None
    fire = fire_id(event_name(payload), payload)
    if not fire and options.part > 1:
        return None
    can_send_whole_copy = len(messages) <= options.entries and (
        fire or len(messages) == 1
    )
    if options.context_from == "payload":
        added = payload_tokens(payload)
        action = claim_action_by_payload(
            session_id, fire, added, bool(can_send_whole_copy)
        )
        return message_for_part(action, options.part, messages, rules)
    transcript_path = payload.get("transcript_path")
    if not transcript_path:
        return None
    tokens = context_tokens(transcript_path, options.context_from)
    if tokens is None:
        if options.part != 1 or event_name(payload).lower() != "userpromptsubmit":
            return None
        return (
            pointer_reminder(rules)
            if transcript_fits_in_tail(transcript_path)
            else None
        )
    action = claim_action(session_id, fire, tokens, bool(can_send_whole_copy))
    return message_for_part(action, options.part, messages, rules)


def event_name(payload):
    return str(payload.get("hook_event_name"))


def forget_baseline(session_id):
    with contextlib.suppress(OSError):
        os.unlink(baseline_path(session_id))


def session_start_reminder(rules, payload, options):
    is_subagent = payload.get("agent_id") or payload.get("subagent_id")
    if options.part == 1 and payload.get("session_id") and not is_subagent:
        forget_baseline(payload["session_id"])
    messages = full_copy_messages(rules, SESSION_START_PREAMBLE)
    if len(messages) > options.entries:
        return pointer_reminder(rules) if options.part == 1 else None
    return message_for_part(COPY, options.part, messages, rules)


def reminder_for(event, payload, options):
    model_names = {
        "fast": options.fast_model,
        "strong": options.strong_model,
        "lead": options.lead_model,
    }
    rules = rules_at(options.rules, model_names)
    if event.lower() in ("sessionstart", "subagentstart"):
        return session_start_reminder(rules, payload, options)
    if payload.get("agent_id") or payload.get("subagent_id"):
        return None
    return growth_reminder(rules, payload, options)


def hook_output(event, reminder, shape):
    if shape == "cursor":
        return {"additional_context": reminder}
    return {
        "hookSpecificOutput": {"hookEventName": event, "additionalContext": reminder}
    }


class QuietArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError(message)


def parsed_options(argv):
    parser = QuietArgumentParser(add_help=False)
    parser.add_argument("part", type=int, nargs="?", default=1)
    parser.add_argument("entries", type=int, nargs="?")
    parser.add_argument("--rules", required=True)
    parser.add_argument("--fast-model")
    parser.add_argument("--strong-model")
    parser.add_argument("--lead-model")
    parser.add_argument(
        "--context-from",
        choices=("transcript", "size", "payload"),
        default="transcript",
    )
    parser.add_argument(
        "--output-shape", choices=("claude", "cursor"), default="claude"
    )
    options = parser.parse_args(argv)
    if options.entries is None:
        options.entries = options.part
    return options


def main():
    options = parsed_options(sys.argv[1:])
    payload = json.loads(sys.stdin.read() or "{}")
    event = payload.get("hook_event_name")
    if not event:
        return
    reminder = reminder_for(event, payload, options)
    if reminder:
        json.dump(hook_output(event, reminder, options.output_shape), sys.stdout)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(0)
