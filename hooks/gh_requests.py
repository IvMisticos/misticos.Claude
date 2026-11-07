import re
from collections.abc import Sequence
from typing import NamedTuple
from urllib.parse import unquote

from gh_arguments import API_COMMAND, PR_COMMAND, GhArguments

FIELD_FLAGS = ("raw-field", "field")
ENDPOINT_SUFFIX = re.compile(r"[?#].*", re.DOTALL)
SKIPPED_SEGMENTS = frozenset({"", "."})
PARENT_SEGMENT = ".."
REPOSITORY_ID = re.compile(r"[0-9]+")


class PrCommand(NamedTuple):
    subcommand: str
    flags: frozenset[str]


class RestRequest(NamedTuple):
    method: str
    resource: tuple[str, ...]
    field_names: frozenset[str]
    reads_input: bool


type GhRequest = PrCommand | RestRequest


def path_segments(endpoint: str) -> list[str]:
    path = unquote(ENDPOINT_SUFFIX.sub("", endpoint))
    segments: list[str] = []
    for segment in path.split("/"):
        if segment == PARENT_SEGMENT:
            segments = segments[:-1]
        elif segment not in SKIPPED_SEGMENTS:
            segments.append(segment)
    return segments


def repository_resource(segments: Sequence[str]) -> tuple[str, ...] | None:
    for index, segment in enumerate(segments):
        if segment == "repos" and len(segments) > index + 3:
            return tuple(segments[index + 3 :])
        by_id = segment == "repositories" and len(segments) > index + 2
        if by_id and REPOSITORY_ID.fullmatch(segments[index + 1]):
            return tuple(segments[index + 2 :])
    return None


def field_name(field: str) -> str:
    return field.partition("=")[0].partition("[")[0]


def http_method(api: GhArguments, sends_a_body: bool) -> str:
    if method := api.last_value("method"):
        return method.upper()
    return "POST" if sends_a_body else "GET"


def rest_request(api: GhArguments) -> RestRequest | None:
    endpoint = api.positionals[0] if api.positionals else ""
    resource = repository_resource(path_segments(endpoint))
    if resource is None:
        return None
    fields = [field for flag in FIELD_FLAGS for field in api.values(flag)]
    reads_input = api.last_value("input") is not None
    method = http_method(api, sends_a_body=bool(fields) or reads_input)
    field_names = frozenset(map(field_name, fields))
    return RestRequest(method, resource, field_names, reads_input)


def gh_request(arguments: GhArguments) -> GhRequest | None:
    command = arguments.command
    if command == (API_COMMAND,):
        return rest_request(arguments)
    if len(command) == 2 and command[0] == PR_COMMAND:
        return PrCommand(command[1], arguments.given_flags())
    return None
