import shlex
from typing import NamedTuple

SHELL_OPERATOR_CHARACTERS = frozenset("();<>|&")
REPO_FLAGS = frozenset({"-R", "--repo"})
CREATE_SUBCOMMANDS = frozenset({"create", "new"})


class GhPrCall(NamedTuple):
    subcommand: str
    target: str
    repo: str

    def creates_a_pull_request(self):
        return self.subcommand in CREATE_SUBCOMMANDS


def words_of(text):
    lexer = shlex.shlex(text, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        return list(lexer)
    except ValueError:
        return []


def command_words(command):
    if isinstance(command, str):
        return words_of(command)
    if isinstance(command, list):
        return [
            word for part in command if isinstance(part, str) for word in words_of(part)
        ]
    return []


def is_shell_operator(word):
    return set(word) <= SHELL_OPERATOR_CHARACTERS


def is_gh(word):
    return word == "gh" or word.endswith("/gh")


def gh_argument_lists(command):
    argument_lists = []
    current = None
    for word in command_words(command):
        if is_shell_operator(word):
            current = None
        elif current is not None:
            current.append(word)
        elif is_gh(word):
            current = []
            argument_lists.append(current)
    return argument_lists


def without_repo_flags(arguments):
    repo = ""
    remaining = []
    words = iter(arguments)
    for word in words:
        if word in REPO_FLAGS:
            repo = next(words, "")
        elif word.startswith("--repo="):
            repo = word.removeprefix("--repo=")
        elif word.startswith("-R"):
            repo = word.removeprefix("-R")
        else:
            remaining.append(word)
    return repo, remaining


def is_flag(word):
    return word.startswith("-")


def gh_pr_call(arguments):
    repo, words = without_repo_flags(arguments)
    if words[:1] != ["pr"]:
        return None
    subcommand_at = next(
        (index for index, word in enumerate(words) if index and not is_flag(word)),
        None,
    )
    if subcommand_at is None:
        return None
    following = words[subcommand_at + 1 : subcommand_at + 2]
    target = following[0] if following and not is_flag(following[0]) else ""
    return GhPrCall(words[subcommand_at], target, repo)


def gh_api_words(arguments):
    return arguments[1:] if arguments[:1] == ["api"] else []
