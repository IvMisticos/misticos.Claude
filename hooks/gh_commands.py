import shlex
from typing import NamedTuple

from bash_commands import command_words

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


def shell_text(command):
    if isinstance(command, str):
        return command
    if isinstance(command, list):
        return shlex.join(part for part in command if isinstance(part, str))
    return ""


def is_gh(word):
    return word == "gh" or word.endswith("/gh")


def gh_argument_lists(command):
    return [
        words[1:] for words in command_words(shell_text(command)) if is_gh(words[0])
    ]


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


def takes_value_before_command(word):
    if word.startswith("--"):
        return "=" not in word
    return len(word) == 2 and is_flag(word)


def command_indexes(words):
    value_expected = False
    for index, word in enumerate(words):
        if value_expected:
            value_expected = False
        elif takes_value_before_command(word):
            value_expected = True
        elif not is_flag(word):
            yield index


def gh_pr_call(arguments):
    repo, words = without_repo_flags(arguments)
    indexes = command_indexes(words)
    pr_at = next(indexes, None)
    if pr_at is None or words[pr_at] != "pr":
        return None
    subcommand_at = next(indexes, None)
    if subcommand_at is None:
        return None
    subcommand = words[subcommand_at]
    target = pr_target(subcommand, words[subcommand_at + 1 :])
    return GhPrCall(subcommand, target, repo)


def gh_api_words(arguments):
    api_at = next(command_indexes(arguments), None)
    if api_at is None or arguments[api_at] != "api":
        return []
    return arguments[api_at + 1 :]
