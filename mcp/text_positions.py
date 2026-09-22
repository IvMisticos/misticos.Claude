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
