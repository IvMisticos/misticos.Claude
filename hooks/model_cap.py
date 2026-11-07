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


def over_cap(
    requested: Model | None, caller: Model | None
) -> tuple[Model, Model] | None:
    if requested is None or caller is None:
        return None
    if requested.family != caller.family:
        higher = requested.rank > caller.rank
    else:
        higher = requested.version > caller.version
    return (requested, caller) if higher else None


def outranks(requested: Model | None, caller: Model | None) -> bool:
    return over_cap(requested, caller) is not None


def full_name(model: Model) -> str:
    return model.name


def capped_input(
    tool_input: JsonObject,
    requested: Model | None,
    caller: Model | None,
    name_of: Callable[[Model], str | None] = full_name,
) -> JsonObject | None:
    pair = over_cap(requested, caller)
    if pair is None:
        return None
    return {**tool_input, "model": name_of(pair[1])}


def denial_reason(
    subject: str, remedy: str, model: Model | None, caller: Model | None
) -> str | None:
    pair = over_cap(model, caller)
    if pair is None:
        return None
    capped, limit = pair
    return f"{subject} runs on {capped.name}, above your {limit.name}. {remedy}"


def project_folders(cwd: Path) -> Iterator[Path]:
    for folder in (cwd, *cwd.parents):
        yield folder
        if (folder / ".git").exists():
            return


def config_folders(cwd: Path, project_subfolder: Path, user_folder: Path) -> list[Path]:
    in_projects = (folder / project_subfolder for folder in project_folders(cwd))
    return [*(folder for folder in in_projects if folder.is_dir()), user_folder]
