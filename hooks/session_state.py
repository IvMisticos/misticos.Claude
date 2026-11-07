import builtins
import contextlib
import json
import os
import re
import sys
import time
import types
import typing
from collections.abc import Callable, Generator
from enum import Enum
from typing import Protocol, TextIO, TypeIs

from json_values import JsonObject, JsonValue

if sys.platform == "win32":
    import msvcrt
else:
    import fcntl

FORGET_AFTER_SECONDS = 7 * 24 * 60 * 60

type Directory = str | os.PathLike[str]


class Record(Protocol):
    def _asdict(self) -> dict[str, object]: ...


def session_file_path(directory: Directory, session_id: str) -> str:
    return os.path.join(directory, re.sub(r"[^A-Za-z0-9_-]", "-", session_id))


def forget_stale_files(directory: Directory) -> None:
    cutoff = time.time() - FORGET_AFTER_SECONDS
    for name in os.listdir(directory):
        path = os.path.join(directory, name)
        try:
            if os.path.getmtime(path) < cutoff:
                os.unlink(path)
        except OSError:
            continue


def lock_exclusively(state_file: TextIO) -> None:
    if sys.platform != "win32":
        fcntl.flock(state_file, fcntl.LOCK_EX)
        return
    state_file.seek(0)
    with contextlib.suppress(OSError):
        msvcrt.locking(state_file.fileno(), msvcrt.LK_LOCK, 1)


@contextlib.contextmanager
def locked_session_file(directory: Directory, session_id: str) -> Generator[TextIO]:
    os.makedirs(directory, exist_ok=True)
    path = session_file_path(directory, session_id)
    if not os.path.exists(path):
        forget_stale_files(directory)
    with open(path, "a+", encoding="utf-8") as state_file:
        lock_exclusively(state_file)
        yield state_file


def read_json(state_file: TextIO) -> JsonValue:
    state_file.seek(0)
    try:
        return json.loads(state_file.read())
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None


def write_json(state_file: TextIO, value: object) -> None:
    state_file.seek(0)
    state_file.truncate()
    json.dump(value, state_file)


def is_record_type(field_type: object) -> TypeIs[type[Record]]:
    return (
        isinstance(field_type, type)
        and issubclass(field_type, tuple)
        and hasattr(field_type, "_fields")
    )


def is_record(value: object) -> TypeIs[Record]:
    return is_record_type(type(value))


def stored_form(value: object) -> object:
    if is_record(value):
        return {name: stored_form(field) for name, field in value._asdict().items()}
    if isinstance(value, tuple):
        return [stored_form(item) for item in value]
    if isinstance(value, dict):
        return {key: stored_form(item) for key, item in value.items()}
    return value


def parsed_union_member(members: tuple[object, ...], stored: JsonValue) -> object:
    for member in members:
        with contextlib.suppress(ValueError):
            return parsed_field(member, stored)
    raise ValueError(f"stored {stored!r} is none of {members}")


def parsed_field(field_type: object, stored: JsonValue) -> object:
    match typing.get_origin(field_type), typing.get_args(field_type):
        case (types.UnionType, members):
            return parsed_union_member(members, stored)
        case (builtins.dict, (key_type, value_type)) if isinstance(stored, dict):
            return {
                parsed_field(key_type, key): parsed_field(value_type, value)
                for key, value in stored.items()
            }
        case (builtins.tuple, (item_type, builtins.Ellipsis)) if isinstance(
            stored, list
        ):
            return tuple(parsed_field(item_type, item) for item in stored)
        case (None, ()) if isinstance(field_type, type) and issubclass(
            field_type, Enum
        ):
            return field_type(stored)
        case (None, ()) if is_record_type(field_type) and isinstance(stored, dict):
            return record_from_fields(field_type, stored)
        case (None, ()) if type(stored) is field_type:
            return stored
    raise ValueError(f"stored {stored!r} is not a {field_type}")


def record_from_fields[R](record_type: Callable[..., R], stored: JsonObject) -> R:
    field_types = typing.get_type_hints(record_type)
    if not stored.keys() <= field_types.keys():
        raise ValueError(f"stored {stored!r} has fields {record_type} lacks")
    fields = {
        name: parsed_field(field_types[name], value) for name, value in stored.items()
    }
    try:
        return record_type(**fields)
    except TypeError as error:
        raise ValueError(f"stored {stored!r} lacks fields of {record_type}") from error


def parsed_record[R](record_type: Callable[..., R], stored: JsonValue) -> R | None:
    if not isinstance(stored, dict):
        return None
    try:
        return record_from_fields(record_type, stored)
    except ValueError:
        return None


def read_record[R: Record](state_file: TextIO, empty_record: R) -> R:
    record = parsed_record(type(empty_record), read_json(state_file))
    return empty_record if record is None else record


def write_record(state_file: TextIO, record: Record) -> None:
    write_json(state_file, stored_form(record))
