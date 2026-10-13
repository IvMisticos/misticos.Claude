import io
import json
import os
from collections.abc import Iterable, Iterator
from typing import NamedTuple

from harnesses import ContextSource
from json_values import JsonObject, JsonValue, dict_or_empty, json_object

type TranscriptPath = str | os.PathLike[str]

TRANSCRIPT_TAIL_BYTES = 1 << 20
CHARS_PER_TOKEN_ESTIMATE = 4
CONTEXT_USAGE_FIELDS = (
    "input_tokens",
    "cache_read_input_tokens",
    "cache_creation_input_tokens",
)


class TranscriptPart(NamedTuple):
    start: int
    lines: bytes

    @property
    def end(self) -> int:
        return self.start + len(self.lines)


def is_conversation_turn(entry: JsonObject) -> bool:
    return (
        not entry.get("isSidechain")
        and dict_or_empty(entry.get("message")).get("model") != "<synthetic>"
    )


def usage_context_tokens(usage: JsonValue) -> int:
    counts = (dict_or_empty(usage).get(field) for field in CONTEXT_USAGE_FIELDS)
    return sum(count for count in counts if isinstance(count, int))


def transcript_tail_lines(transcript_path: TranscriptPath) -> list[bytes]:
    with open(transcript_path, "rb") as transcript:
        transcript.seek(0, os.SEEK_END)
        start = max(0, transcript.tell() - TRANSCRIPT_TAIL_BYTES)
        transcript.seek(start)
        lines = transcript.read().split(b"\n")
    return lines if start == 0 else lines[1:]


def bytes_from(transcript_path: TranscriptPath, offset: int) -> tuple[int, bytes]:
    with open(transcript_path, "rb") as transcript:
        size = transcript.seek(0, os.SEEK_END)
        start = offset if offset <= size else 0
        transcript.seek(start)
        return start, transcript.read()


def complete_lines(data: bytes) -> bytes:
    return data[: data.rfind(b"\n") + 1]


def transcript_part_from(
    transcript_path: TranscriptPath, offset: int
) -> TranscriptPart:
    try:
        start, data = bytes_from(transcript_path, offset)
    except OSError:
        return TranscriptPart(offset, b"")
    return TranscriptPart(start, complete_lines(data))


def entries_in(lines: Iterable[bytes]) -> Iterator[JsonObject]:
    for line in lines:
        entry = json_object(line)
        if entry is not None:
            yield entry


def tail_entries(transcript_path: TranscriptPath) -> Iterator[JsonObject]:
    try:
        lines = transcript_tail_lines(transcript_path)
    except OSError:
        return
    yield from entries_in(lines)


def positioned_entries(part: TranscriptPart) -> Iterator[tuple[int, JsonObject]]:
    position = part.start
    for line in io.BytesIO(part.lines):
        entry = json_object(line)
        if entry is not None:
            yield position, entry
        position += len(line)


def recent_entries(transcript_path: TranscriptPath) -> Iterator[JsonObject]:
    for entry in reversed(list(tail_entries(transcript_path))):
        if entry.get("type") == "assistant":
            yield entry


def latest_context_tokens(transcript_path: TranscriptPath) -> int | None:
    for entry in recent_entries(transcript_path):
        if not is_conversation_turn(entry):
            continue
        tokens = usage_context_tokens(dict_or_empty(entry.get("message")).get("usage"))
        if tokens:
            return tokens
    return None


def context_tokens_from_size(transcript_path: TranscriptPath) -> int | None:
    try:
        return os.path.getsize(transcript_path) // CHARS_PER_TOKEN_ESTIMATE or None
    except OSError:
        return None


def payload_tokens(payload: JsonObject) -> int:
    tool_text = json.dumps(payload.get("tool_input")) + str(
        payload.get("tool_output") or ""
    )
    return len(tool_text) // CHARS_PER_TOKEN_ESTIMATE


def context_tokens(
    transcript_path: TranscriptPath, source: ContextSource
) -> int | None:
    match source:
        case ContextSource.SIZE:
            return context_tokens_from_size(transcript_path)
        case _:
            return latest_context_tokens(transcript_path)
