import io
import re
import shlex
from typing import NamedTuple

SHELL_OPERATOR_CHARACTERS = "();<>|&\n"
WORD_SEPARATORS = " \t\r"
LINE_CONTINUATION = re.compile(r"(?<!\\)((?:\\\\)*)\\\n")
FD_BEFORE_REDIRECTION = re.compile(r"(?<![^\s();<>|&])\d+(?=[<>])")
REPO_FLAGS = frozenset({"-R", "--repo"})
CREATE_SUBCOMMANDS = frozenset({"create", "new"})
SHARED_VALUED_FLAGS = frozenset(
    {
        "-b",
        "--body",
        "-F",
        "--body-file",
        "-t",
        "--title",
        "--template",
        "--subject",
        "-q",
        "--jq",
        "--json",
    }
)
EDIT_VALUED_FLAGS = frozenset(
    {
        "-B",
        "--base",
        "-m",
        "--milestone",
        "--add-assignee",
        "--add-label",
        "--add-project",
        "--add-reviewer",
        "--remove-assignee",
        "--remove-label",
        "--remove-project",
        "--remove-reviewer",
    }
)
VALUED_FLAGS_BY_TARGETED_SUBCOMMAND = {
    "checkout": SHARED_VALUED_FLAGS | {"--branch"},
    "checks": SHARED_VALUED_FLAGS | {"-i", "--interval"},
    "close": SHARED_VALUED_FLAGS | {"-c", "--comment"},
    "comment": SHARED_VALUED_FLAGS,
    "diff": SHARED_VALUED_FLAGS | {"--color", "-e", "--exclude"},
    "edit": SHARED_VALUED_FLAGS | EDIT_VALUED_FLAGS,
    "lock": SHARED_VALUED_FLAGS | {"-r", "--reason"},
    "merge": SHARED_VALUED_FLAGS | {"-A", "--author-email", "--match-head-commit"},
    "ready": SHARED_VALUED_FLAGS,
    "reopen": SHARED_VALUED_FLAGS | {"-c", "--comment"},
    "revert": SHARED_VALUED_FLAGS,
    "review": SHARED_VALUED_FLAGS,
    "unlock": SHARED_VALUED_FLAGS,
    "update-branch": SHARED_VALUED_FLAGS,
    "view": SHARED_VALUED_FLAGS,
}


class GhPrCall(NamedTuple):
    subcommand: str
    target: str | None
    repo: str | None

    def creates_a_pull_request(self):
        return self.subcommand in CREATE_SUBCOMMANDS


class CommentEndingBeforeNewline(io.StringIO):
    def readline(self, size=-1):
        line = super().readline(size)
        if not line.endswith("\n"):
            return line
        self.seek(self.tell() - 1)
        return line.removesuffix("\n")


def shell_text(text):
    joined = LINE_CONTINUATION.sub(r"\1", text)
    return FD_BEFORE_REDIRECTION.sub("", joined)


def words_of(text):
    lexer = shlex.shlex(
        CommentEndingBeforeNewline(shell_text(text)),
        posix=True,
        punctuation_chars=SHELL_OPERATOR_CHARACTERS,
    )
    lexer.whitespace = WORD_SEPARATORS
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
    return set(word) <= set(SHELL_OPERATOR_CHARACTERS)


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


def is_flag(word):
    return word.startswith("-")


def positionals(words, flags_with_values):
    remaining = iter(words)
    for word in remaining:
        if word in flags_with_values:
            next(remaining, None)
        elif not is_flag(word):
            yield word


def pr_target(subcommand, following):
    flags_with_values = VALUED_FLAGS_BY_TARGETED_SUBCOMMAND.get(subcommand)
    if flags_with_values is None:
        return None
    return next(positionals(following, flags_with_values), None)


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
    subcommand = words[subcommand_at]
    target = pr_target(subcommand, words[subcommand_at + 1 :])
    return GhPrCall(subcommand, target, repo)


def gh_api_words(arguments):
    return arguments[1:] if arguments[:1] == ["api"] else []
