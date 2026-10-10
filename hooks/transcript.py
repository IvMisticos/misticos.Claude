import json
import os

TRANSCRIPT_TAIL_BYTES = 1 << 20
CHARS_PER_TOKEN_ESTIMATE = 4
CONTEXT_USAGE_FIELDS = (
    "input_tokens",
    "cache_read_input_tokens",
    "cache_creation_input_tokens",
)


def dict_or_empty(value):
    return value if isinstance(value, dict) else {}


def is_conversation_turn(entry):
    return (
        not entry.get("isSidechain")
        and dict_or_empty(entry.get("message")).get("model") != "<synthetic>"
    )


def usage_context_tokens(usage):
    counts = (dict_or_empty(usage).get(field) for field in CONTEXT_USAGE_FIELDS)
    return sum(count for count in counts if isinstance(count, int))


def transcript_tail_lines(transcript_path):
    with open(transcript_path, "rb") as transcript:
        transcript.seek(0, os.SEEK_END)
        start = max(0, transcript.tell() - TRANSCRIPT_TAIL_BYTES)
        transcript.seek(start)
        lines = transcript.read().split(b"\n")
    return lines if start == 0 else lines[1:]


def recent_entries(transcript_path):
    try:
        lines = transcript_tail_lines(transcript_path)
    except OSError:
        return
    for line in reversed(lines):
        try:
            entry = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        if isinstance(entry, dict) and entry.get("type") == "assistant":
            yield entry


def latest_context_tokens(transcript_path):
    for entry in recent_entries(transcript_path):
        if not is_conversation_turn(entry):
            continue
        tokens = usage_context_tokens(dict_or_empty(entry.get("message")).get("usage"))
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


def context_tokens(transcript_path, source):
    if source == "size":
        return context_tokens_from_size(transcript_path)
    return latest_context_tokens(transcript_path)
