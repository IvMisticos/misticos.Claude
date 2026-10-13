import functools
import os
import re
from pathlib import Path
from urllib.parse import unquote, urlparse
from urllib.request import pathname2url

from lsp_types import Position

LINE_BREAK = re.compile(r"\r\n|\r|\n")


def to_uri(path: str | os.PathLike[str]) -> str:
    return "file://" + pathname2url(str(path))


def from_uri(uri: str) -> Path:
    return Path(unquote(urlparse(uri).path))


def utf16_length(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def utf16_offset_to_index(line_text: str, utf16_offset: int) -> int:
    units = 0
    for index, character in enumerate(line_text):
        if units >= utf16_offset:
            return index
        units += utf16_length(character)
    return len(line_text)


def lsp_position(text: str, line: int, column: int) -> Position:
    lines = LINE_BREAK.split(text)
    line_text = lines[line - 1] if 0 < line <= len(lines) else ""
    return {
        "line": line - 1,
        "character": utf16_length(line_text[: column - 1]),
    }


def position_key(position: Position) -> tuple[int, int]:
    return position["line"], position["character"]


def read_text(path: str | os.PathLike[str]) -> str:
    with open(path, encoding="utf-8", newline="") as file:
        return file.read()


def lines_of(path: Path) -> list[str]:
    stat = os.stat(path)
    return cached_lines(str(path), stat.st_mtime_ns, stat.st_size)


@functools.lru_cache(maxsize=256)
def cached_lines(path: str, mtime_ns: int, size: int) -> list[str]:
    return LINE_BREAK.split(read_text(Path(path)))
