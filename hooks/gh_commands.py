import io
import shlex
from typing import NamedTuple

COMMAND_SEPARATORS = "();<>|&\n"
WORD_SEPARATORS = " \t\r"
LINE_CONTINUATION = "\\\n"
REPO_FLAGS = frozenset({"-R", "--repo"})
CREATE_SUBCOMMANDS = frozenset({"create", "new"})


class GhPrCall(NamedTuple):
    subcommand: str
    target: str | None
    repo: str | None

    def creates_a_pull_request(self):
        return self.subcommand in CREATE_SUBCOMMANDS


class CommentsKeepLineBreaks(io.StringIO):
    def readline(self):
        line = super().readline()
        if line.endswith("\n"):
            self.seek(self.tell() - 1)
        return line


def shell_tokens(command):
    joined_lines = command.replace(LINE_CONTINUATION, "")
    lexer = shlex.shlex(
        CommentsKeepLineBreaks(joined_lines),
        posix=True,
        punctuation_chars=COMMAND_SEPARATORS,
    )
    lexer.whitespace = WORD_SEPARATORS
    lexer.whitespace_split = True
    try:
        return list(lexer)
    except ValueError:
        return []


def command_tokens(command):
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


def is_command_separator(token):
    return bool(token) and not token.strip(COMMAND_SEPARATORS)


def is_gh(word):
    return word == "gh" or word.endswith("/gh")


def gh_argument_lists(command):
    argument_lists = []
    current = None
    for token in command_tokens(command):
        if is_command_separator(token):
            current = None
        elif current is not None:
            current.append(token)
        elif is_gh(token):
            current = []
            argument_lists.append(current)
    return argument_lists


def without_repo_flags(arguments):
    repo = None
    remaining = []
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


def pr_target(words_after_subcommand):
    if not words_after_subcommand or words_after_subcommand[0].startswith("-"):
        return None
    return words_after_subcommand[0]


def gh_pr_call(arguments):
    repo, words = without_repo_flags(arguments)
    if len(words) < 2 or words[0] != "pr":
        return None
    return GhPrCall(words[1], pr_target(words[2:]), repo)


def gh_api_words(arguments):
    if arguments[:1] != ["api"]:
        return []
    return arguments[1:]
