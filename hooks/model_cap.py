import re
from typing import NamedTuple

from json_values import JsonValue


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

DATE_DIGITS = 8


class Model(NamedTuple):
    name: str
    rank: int
    family: str
    version: tuple[int, ...]


def version(name: str) -> tuple[int, ...]:
    slug = name.split("[", 1)[0]
    numbers = re.findall(r"\d+", slug)
    return tuple(int(number) for number in numbers if len(number) < DATE_DIGITS)


def parsed_model(value: JsonValue) -> Model | None:
    if not isinstance(value, str):
        return None
    words = set(re.split(r"[^a-z]+", value.lower()))
    models = (
        Model(value, rank, family, version(value))
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
