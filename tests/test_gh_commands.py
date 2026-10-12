import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hooks"))

import pytest
from gh_commands import GhPrCall, gh_api_words, gh_argument_lists, gh_pr_call
from pull_requests import pull_request_of_gh_pr_call


def test_missing_target_and_repo_are_none():
    assert gh_pr_call(["pr", "list"]) == GhPrCall("list", None, None)


@pytest.mark.parametrize("arguments", [["-R"], ["--repo"], ["--repo="], ["-R", ""]])
def test_repo_flag_without_value_leaves_repo_none(arguments):
    assert gh_pr_call(["pr", "view", "1", *arguments]) == GhPrCall("view", "1", None)


@pytest.mark.parametrize(
    "call", [GhPrCall("list", None, "o/r"), GhPrCall("view", "1", None)]
)
def test_call_without_target_or_repo_names_no_pull_request(call):
    assert pull_request_of_gh_pr_call(call) is None


@pytest.mark.parametrize(
    ("command", "call"),
    [
        ("gh pr merge 12 --squash", GhPrCall("merge", "12", None)),
        (
            "gh pr view https://github.com/o/r/pull/5",
            GhPrCall("view", "https://github.com/o/r/pull/5", None),
        ),
        ("gh -R o/r pr comment 7 -b x", GhPrCall("comment", "7", "o/r")),
        ("gh pr comment --body 3", GhPrCall("comment", None, None)),
    ],
)
def test_pr_target_is_the_word_after_the_subcommand(command, call):
    [arguments] = gh_argument_lists(command)
    assert gh_pr_call(arguments) == call


def test_api_words_follow_api():
    [arguments] = gh_argument_lists("gh api repos/o/r/pulls/3/comments")
    assert gh_api_words(arguments) == ["repos/o/r/pulls/3/comments"]


@pytest.mark.parametrize(
    ("command", "argument_lists"),
    [
        (
            "gh pr view 1 # gh pr close 1\ngh pr view 2",
            [["pr", "view", "1"], ["pr", "view", "2"]],
        ),
        ("# gh pr close 1\ngh pr view 2", [["pr", "view", "2"]]),
        ('gh pr comment 1 --body "# x"', [["pr", "comment", "1", "--body", "# x"]]),
        (
            "gh pr view 1 # it's open\ngh pr view 2",
            [["pr", "view", "1"], ["pr", "view", "2"]],
        ),
    ],
)
def test_comments_end_at_the_line_break(command, argument_lists):
    assert gh_argument_lists(command) == argument_lists


@pytest.mark.parametrize(
    ("command", "argument_lists"),
    [
        ("gh pr view 1 \\\n  -R o/r", [["pr", "view", "1", "-R", "o/r"]]),
        (
            'gh pr comment 1 --body "a 2>b" -R o/r',
            [["pr", "comment", "1", "--body", "a 2>b", "-R", "o/r"]],
        ),
        (
            "gh pr view 1 >/dev/null; gh pr view 2",
            [["pr", "view", "1"], ["pr", "view", "2"]],
        ),
        ("cd x && gh pr view 1 | head", [["pr", "view", "1"]]),
        ("gh pr comment 1 --body \"it's", []),
    ],
)
def test_commands_split_at_shell_operators(command, argument_lists):
    assert gh_argument_lists(command) == argument_lists


@pytest.mark.parametrize("body", ['""', '"a; b"', "'a && b'", '"a\nb"'])
def test_quoted_operators_stay_inside_the_gh_call(body):
    command = f"gh pr comment 1 --body {body} -R o/r"
    assert gh_argument_lists(command)[0][-2:] == ["-R", "o/r"]
