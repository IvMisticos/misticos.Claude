import builtins
import contextlib
import json
import os
import re
import sys
import time
import typing
from collections.abc import Callable, Generator
from enum import Enum
from typing import Protocol, TextIO

from json_values import JsonValue

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


def parsed_field(field_type: object, stored: JsonValue) -> object:
    match typing.get_origin(field_type), typing.get_args(field_type):
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
        case (None, ()) if type(stored) is field_type:
            return stored
    raise ValueError(f"stored {stored!r} is not a {field_type}")


def parsed_record[R](record_type: Callable[..., R], stored: JsonValue) -> R | None:
    if not isinstance(stored, dict):
        return None
    field_types = typing.get_type_hints(record_type)
    if not stored.keys() <= field_types.keys():
        return None
    try:
        fields = {
            name: parsed_field(field_types[name], value)
            for name, value in stored.items()
        }
        return record_type(**fields)
    except (ValueError, TypeError):
        return None


def read_record[R: Record](state_file: TextIO, empty_record: R) -> R:
    record = parsed_record(type(empty_record), read_json(state_file))
    return empty_record if record is None else record


def write_record(state_file: TextIO, record: Record) -> None:
    write_json(state_file, record._asdict())
