import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import NamedTuple

from gh_commands import OPTIONS_END, gh_command_words

API_LONG_FLAGS_WITH_VALUE = frozenset(
    {
        "--cache",
        "--field",
        "--header",
        "--hostname",
        "--input",
        "--jq",
        "--method",
        "--preview",
        "--raw-field",
        "--template",
    }
)
API_SHORT_FLAGS_WITH_VALUE = frozenset("XfFHqtp")
METHOD_FLAGS = frozenset({"-X", "--method"})
RAW_FIELD_FLAGS = frozenset({"-f", "--raw-field"})
TYPED_FIELD_FLAGS = frozenset({"-F", "--field"})
FIELD_FLAGS = RAW_FIELD_FLAGS | TYPED_FIELD_FLAGS
INPUT_FLAG = "--input"
QUERY_FIELD_PREFIX = "query="
FILE_VALUE_PREFIX = "@"
ENDPOINT_SUFFIX = re.compile(r"[?#].*", re.DOTALL)
REPOSITORY_RESOURCE = re.compile(
    r"(?:^|/)(?:repos/[^/]+/[^/]+|repositories/[0-9]+)/(?P<resource>.+)$", re.DOTALL
)


class PrCommand(NamedTuple):
    subcommand: str
    arguments: tuple[str, ...]


class RestRequest(NamedTuple):
    method: str
    resource: str
    field_names: frozenset[str]
    reads_input: bool


class GraphqlRequest(NamedTuple):
    query: str
    fields: tuple[str, ...]


@dataclass(frozen=True)
class GraphqlQueryFromFile:
    pass


type ApiRequest = RestRequest | GraphqlRequest | GraphqlQueryFromFile
type GhRequest = PrCommand | ApiRequest


class ApiFlag(NamedTuple):
    name: str
    value: str


class ApiField(NamedTuple):
    text: str
    typed: bool

    @property
    def name(self) -> str:
        return self.text.partition("=")[0].partition("[")[0]

    def reads_query_from_file(self) -> bool:
        return self.typed and self.text.startswith(
            QUERY_FIELD_PREFIX + FILE_VALUE_PREFIX
        )


class ApiArguments(NamedTuple):
    flags: tuple[ApiFlag, ...]
    positionals: tuple[str, ...]

    def endpoint_path(self) -> str:
        endpoint = self.positionals[1] if len(self.positionals) > 1 else ""
        return ENDPOINT_SUFFIX.sub("", endpoint).removesuffix("/")

    def fields(self) -> list[ApiField]:
        return [
            ApiField(flag.value, flag.name in TYPED_FIELD_FLAGS)
            for flag in self.flags
            if flag.name in FIELD_FLAGS
        ]

    def reads_input(self) -> bool:
        return any(flag.name == INPUT_FLAG for flag in self.flags)

    def method(self) -> str:
        named = [flag.value for flag in self.flags if flag.name in METHOD_FLAGS]
        if named and named[-1]:
            return named[-1].upper()
        return "POST" if self.fields() or self.reads_input() else "GET"

    def query(self) -> str:
        queries = [
            field.text.removeprefix(QUERY_FIELD_PREFIX)
            for field in self.fields()
            if field.text.startswith(QUERY_FIELD_PREFIX)
        ]
        return queries[-1] if queries else ""

    def reads_query_from_file(self) -> bool:
        from_field = any(field.reads_query_from_file() for field in self.fields())
        return from_field or self.reads_input()


def flag_with_next_word(name: str, words: Iterator[str]) -> tuple[ApiFlag, ...]:
    value = next(words, None)
    return () if value is None else (ApiFlag(name, value),)


def long_api_flag(word: str, words: Iterator[str]) -> tuple[ApiFlag, ...]:
    name, has_value, value = word.partition("=")
    if has_value:
        return (ApiFlag(name, value),)
    if name in API_LONG_FLAGS_WITH_VALUE:
        return flag_with_next_word(name, words)
    return ()


def short_api_flag(word: str, words: Iterator[str]) -> tuple[ApiFlag, ...]:
    letters = word.removeprefix("-")
    for index, letter in enumerate(letters):
        name = f"-{letter}"
        rest = letters[index + 1 :]
        if rest.startswith("="):
            return (ApiFlag(name, rest.removeprefix("=")),)
        if letter in API_SHORT_FLAGS_WITH_VALUE:
            return (ApiFlag(name, rest),) if rest else flag_with_next_word(name, words)
    return ()


def api_arguments(arguments: Sequence[str]) -> ApiArguments:
    flags: list[ApiFlag] = []
    positionals: list[str] = []
    words = iter(arguments)
    for word in words:
        if word == OPTIONS_END:
            positionals.extend(words)
        elif word.startswith("--"):
            flags.extend(long_api_flag(word, words))
        elif word.startswith("-") and word != "-":
            flags.extend(short_api_flag(word, words))
        else:
            positionals.append(word)
    return ApiArguments(tuple(flags), tuple(positionals))


def is_graphql(path: str) -> bool:
    return path == "graphql" or path.endswith("/graphql")


def graphql_request(api: ApiArguments) -> GraphqlRequest | GraphqlQueryFromFile:
    if api.reads_query_from_file():
        return GraphqlQueryFromFile()
    return GraphqlRequest(api.query(), tuple(field.text for field in api.fields()))


def rest_request(api: ApiArguments) -> RestRequest | None:
    found = REPOSITORY_RESOURCE.search(api.endpoint_path())
    if found is None:
        return None
    field_names = frozenset(field.name for field in api.fields())
    return RestRequest(api.method(), found["resource"], field_names, api.reads_input())


def api_request(arguments: Sequence[str]) -> ApiRequest | None:
    api = api_arguments(arguments)
    if is_graphql(api.endpoint_path()):
        return graphql_request(api)
    return rest_request(api)


def gh_request(arguments: Sequence[str]) -> GhRequest | None:
    match gh_command_words(arguments):
        case ["pr", subcommand]:
            return PrCommand(subcommand, tuple(arguments))
        case ["api", *_]:
            return api_request(arguments)
    return None
