import re
import shlex
from collections.abc import Iterable, Sequence
from typing import NamedTuple

from json_values import JsonValue

COMMAND_SEPARATORS = "();<>|&\n"
WORD_SEPARATORS = " \t\r"
LINE_CONTINUATION = "\\\n"
REDIRECTED_FILE_DESCRIPTOR = re.compile(r"(?<!\S)\d+(?=[<>])")
REPO_FLAGS = frozenset({"-R", "--repo"})
CREATE_SUBCOMMANDS = frozenset({"create", "new"})


class GhPrCall(NamedTuple):
    subcommand: str
    target: str | None
    repo: str | None

    def creates_a_pull_request(self) -> bool:
        return self.subcommand in CREATE_SUBCOMMANDS


def shell_tokens(command: str) -> list[str]:
    joined_lines = command.replace(LINE_CONTINUATION, "")
    without_descriptors = REDIRECTED_FILE_DESCRIPTOR.sub("", joined_lines)
    lexer = shlex.shlex(
        without_descriptors,
        posix=True,
        punctuation_chars=COMMAND_SEPARATORS,
    )
    lexer.whitespace = WORD_SEPARATORS
    lexer.whitespace_split = True
    lexer.commenters = ""
    try:
        return list(lexer)
    except ValueError:
        return []


def command_tokens(command: JsonValue) -> list[str]:
    if isinstance(command, str):
        return shell_tokens(command)
    if isinstance(command, list):
        return [
            token
            for part in command
            if isinstance(part, str)
            for token in shell_tokens(part)
        ]
    return []


def is_command_separator(token: str) -> bool:
    return bool(token) and not token.strip(COMMAND_SEPARATORS)


def is_gh(word: str) -> bool:
    return word == "gh" or word.endswith("/gh")


def gh_argument_lists(command: JsonValue) -> list[list[str]]:
    argument_lists: list[list[str]] = []
    current: list[str] | None = None
    for token in command_tokens(command):
        if is_command_separator(token):
            current = None
        elif current is not None:
            current.append(token)
        elif is_gh(token):
            current = []
            argument_lists.append(current)
    return argument_lists


def without_repo_flags(arguments: Iterable[str]) -> tuple[str | None, list[str]]:
    repo: str | None = None
    remaining: list[str] = []
    words = iter(arguments)
    for word in words:
        if word in REPO_FLAGS:
            repo = next(words, None)
        elif word.startswith("--repo="):
            repo = word.removeprefix("--repo=")
        elif word.startswith("-R"):
            repo = word.removeprefix("-R")
        else:
            remaining.append(word)
    return repo or None, remaining


def pr_target(words_after_subcommand: Sequence[str]) -> str | None:
    if not words_after_subcommand or words_after_subcommand[0].startswith("-"):
        return None
    return words_after_subcommand[0]


def gh_pr_call(arguments: Sequence[str]) -> GhPrCall | None:
    repo, words = without_repo_flags(arguments)
    if len(words) < 2 or words[0] != "pr":
        return None
    return GhPrCall(words[1], pr_target(words[2:]), repo)


def gh_api_words(arguments: list[str]) -> list[str]:
    if arguments[:1] != ["api"]:
        return []
    return arguments[1:]
