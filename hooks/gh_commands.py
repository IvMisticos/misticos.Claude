import re
import shlex
from collections.abc import Sequence
from typing import NamedTuple

from gh_arguments import API_COMMAND, CREATE_SUBCOMMANDS, PR_COMMAND, gh_arguments
from json_values import JsonValue

COMMAND_SEPARATORS = "();<>|&\n"
WORD_SEPARATORS = " \t\r"
LINE_CONTINUATION = "\\\n"
REDIRECTED_FILE_DESCRIPTOR = re.compile(r"(?<!\S)\d+(?=[<>])")


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


def gh_pr_call(arguments: Sequence[str]) -> GhPrCall | None:
    parsed = gh_arguments(arguments)
    if len(parsed.command) < 2 or parsed.command[0] != PR_COMMAND:
        return None
    target = parsed.positionals[0] if parsed.positionals else None
    return GhPrCall(parsed.command[1], target, parsed.last_value("repo") or None)


def gh_api_words(arguments: Sequence[str]) -> list[str]:
    parsed = gh_arguments(arguments)
    if parsed.command != (API_COMMAND,):
        return []
    return [*parsed.positionals, *parsed.option_values()]
