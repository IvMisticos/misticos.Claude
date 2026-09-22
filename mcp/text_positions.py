import functools
import os
import re
from pathlib import Path
from urllib.parse import unquote, urlparse
from urllib.request import pathname2url

LINE_BREAK = re.compile(r"\r\n|\r|\n")


def to_uri(path):
    return "file://" + pathname2url(str(path))


def from_uri(uri):
    return Path(unquote(urlparse(uri).path))


def utf16_length(text):
    return len(text.encode("utf-16-le")) // 2


def utf16_offset_to_index(line_text, utf16_offset):
    units = 0
    for index, character in enumerate(line_text):
        if units >= utf16_offset:
            return index
        units += utf16_length(character)
    return len(line_text)


def read_text(path):
    with open(path, encoding="utf-8", newline="") as file:
        return file.read()


def lines_of(path):
    stat = os.stat(path)
    return cached_lines(str(path), stat.st_mtime_ns, stat.st_size)


@functools.lru_cache(maxsize=256)
def cached_lines(path, mtime_ns, size):
    return LINE_BREAK.split(read_text(Path(path)))


def apply_workspace_edit(edit):
    document_changes = edit.get("documentChanges") or []
    for change in document_changes:
        if "textDocument" not in change:
            raise ValueError(
                f"the language server wants a file operation ({change.get('kind')}) that this tool does not apply; nothing was written"
            )
    changed = []
    for uri, edits in (edit.get("changes") or {}).items():
        changed.append(apply_text_edits(from_uri(uri), edits))
    for change in document_changes:
        changed.append(
            apply_text_edits(from_uri(change["textDocument"]["uri"]), change["edits"])
        )
    return changed


def apply_text_edits(path, edits):
    text = read_text(path)
    lines = LINE_BREAK.split(text)
    offsets = line_offsets(text)
    for edit in sorted(
        edits,
        key=lambda e: (e["range"]["start"]["line"], e["range"]["start"]["character"]),
        reverse=True,
    ):
        start = text_offset(lines, offsets, edit["range"]["start"])
        end = text_offset(lines, offsets, edit["range"]["end"])
        text = text[:start] + edit["newText"] + text[end:]
    with open(path, "w", encoding="utf-8", newline="") as file:
        file.write(text)
    return str(path)


def text_offset(lines, offsets, position):
    if position["line"] >= len(lines):
        return offsets[-1] + len(lines[-1])
    return offsets[position["line"]] + utf16_offset_to_index(
        lines[position["line"]], position["character"]
    )


def line_offsets(text):
    offsets = [0]
    for match in LINE_BREAK.finditer(text):
        offsets.append(match.end())
    return offsets
