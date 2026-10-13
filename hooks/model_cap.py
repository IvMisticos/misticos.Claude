import re
from collections.abc import Iterator
from pathlib import Path

from json_values import JsonValue

TIER_LEVELS = (
    ("haiku",),
    ("sonnet", "luna"),
    ("terra",),
    ("opus", "opusplan", "sol"),
    ("fable", "best", "astra"),
)

DATE_DIGITS = 8


def model_words(model: JsonValue) -> set[str]:
    return set(re.split(r"[^a-z]+", str(model or "").lower()))


def tier_rank(model: JsonValue) -> int | None:
    words = model_words(model)
    return next(
        (rank for rank, level in enumerate(TIER_LEVELS) if words.intersection(level)),
        None,
    )


def tier_name(model: JsonValue) -> str | None:
    words = model_words(model)
    return next(
        (word for level in TIER_LEVELS for word in level if word in words), None
    )


def version(model: JsonValue) -> tuple[int, ...]:
    slug = str(model or "").split("[", 1)[0]
    numbers = re.findall(r"\d+", slug)
    return tuple(int(number) for number in numbers if len(number) < DATE_DIGITS)


def outranks(requested: JsonValue, caller: JsonValue) -> bool:
    requested_rank = tier_rank(requested)
    caller_rank = tier_rank(caller)
    if requested_rank is None or caller_rank is None:
        return False
    if requested_rank != caller_rank or tier_name(requested) != tier_name(caller):
        return requested_rank > caller_rank
    return bool(version(requested)) and version(requested) > version(caller)


def project_folders(cwd: Path) -> Iterator[Path]:
    for folder in (cwd, *cwd.parents):
        yield folder
        if (folder / ".git").exists():
            return
