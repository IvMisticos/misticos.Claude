import re
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import NamedTuple

from json_values import JsonObject, JsonValue

DATE_DIGITS = 8


class Tier(NamedTuple):
    claude_alias: str | None
    families: tuple[str, ...]


TIERS = (
    Tier("haiku", ("haiku",)),
    Tier("sonnet", ("sonnet", "luna")),
    Tier(None, ("terra",)),
    Tier("opus", ("opus", "opusplan", "sol")),
    Tier("fable", ("fable", "best", "astra")),
)


class Model(NamedTuple):
    name: str
    rank: int
    family: str
    version: tuple[int, ...]


def version_of(name: str) -> tuple[int, ...]:
    numbers = re.findall(r"\d+", name.split("[", 1)[0])
    return tuple(int(number) for number in numbers if len(number) < DATE_DIGITS)


def parsed_model(value: JsonValue) -> Model | None:
    if not isinstance(value, str):
        return None
    words = set(re.split(r"[^a-z]+", value.lower()))
    models = (
        Model(value, rank, family, version_of(value))
        for rank, tier in enumerate(TIERS)
        for family in tier.families
        if family in words
    )
    return next(models, None)


def claude_alias(model: Model | None) -> str | None:
    return TIERS[model.rank].claude_alias if model else None


def outranks(requested: Model | None, caller: Model | None) -> bool:
    if requested is None or caller is None:
        return False
    if requested.family != caller.family:
        return requested.rank > caller.rank
    return requested.version > caller.version


def full_name(model: Model) -> str:
    return model.name


def capped_input(
    tool_input: JsonObject,
    requested: Model | None,
    caller: Model | None,
    name_of: Callable[[Model], str | None] = full_name,
) -> JsonObject | None:
    if caller is None or not outranks(requested, caller):
        return None
    return {**tool_input, "model": name_of(caller)}


def project_folders(cwd: Path) -> Iterator[Path]:
    for folder in (cwd, *cwd.parents):
        yield folder
        if (folder / ".git").exists():
            return
