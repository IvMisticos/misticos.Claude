import pytest
from gh_commands import GhPrCall, gh_api_words, gh_argument_lists, gh_pr_call
from pull_requests import pull_request_of_gh_pr_call


def test_missing_target_and_repo_are_none() -> None:
    assert gh_pr_call(["pr", "list"]) == GhPrCall("list", None, None)


@pytest.mark.parametrize("arguments", [["-R"], ["--repo"], ["--repo="], ["-R", ""]])
def test_repo_flag_without_value_leaves_repo_none(arguments: list[str]) -> None:
    assert gh_pr_call(["pr", "view", "1", *arguments]) == GhPrCall("view", "1", None)


@pytest.mark.parametrize(
    "call", [GhPrCall("list", None, "o/r"), GhPrCall("view", "1", None)]
)
def test_call_without_target_or_repo_names_no_pull_request(call: GhPrCall) -> None:
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
def test_pr_target_is_the_word_after_the_subcommand(
    command: str, call: GhPrCall
) -> None:
    [arguments] = gh_argument_lists(command)
    assert gh_pr_call(arguments) == call


def test_api_words_follow_api() -> None:
    [arguments] = gh_argument_lists("gh api repos/o/r/pulls/3/comments")
    assert gh_api_words(arguments) == ["repos/o/r/pulls/3/comments"]


@pytest.mark.parametrize(
    ("command", "argument_lists"),
    [
        ("gh pr comment 1 --body a#b", [["pr", "comment", "1", "--body", "a#b"]]),
        ("gh pr view 1 -R o/r # note", [["pr", "view", "1", "-R", "o/r", "#", "note"]]),
    ],
)
def test_hash_is_an_ordinary_character(
    command: str, argument_lists: list[list[str]]
) -> None:
    assert gh_argument_lists(command) == argument_lists


@pytest.mark.parametrize(
    ("command", "argument_lists"),
    [
        ("gh pr view 1 \\\n  -R o/r", [["pr", "view", "1", "-R", "o/r"]]),
        (
            'gh pr comment 1 --body "a > b" -R o/r',
            [["pr", "comment", "1", "--body", "a > b", "-R", "o/r"]],
        ),
        (
            "gh pr view 1 >/dev/null; gh pr view 2",
            [["pr", "view", "1"], ["pr", "view", "2"]],
        ),
        ("cd x && gh pr view 1 | head", [["pr", "view", "1"]]),
        ("gh pr comment 1 --body \"it's", []),
    ],
)
def test_commands_split_at_shell_operators(
    command: str, argument_lists: list[list[str]]
) -> None:
    assert gh_argument_lists(command) == argument_lists


@pytest.mark.parametrize(
    ("command", "argument_lists"),
    [
        (
            "gh pr view 1 2>/dev/null; gh pr view 2",
            [["pr", "view", "1"], ["pr", "view", "2"]],
        ),
        ("gh pr checks -R o/r 2>&1 | tail", [["pr", "checks", "-R", "o/r"]]),
        ("gh -R o/r pr list 2>/dev/null", [["-R", "o/r", "pr", "list"]]),
        ("gh -R o/r pr status 2>&1", [["-R", "o/r", "pr", "status"]]),
        ("gh pr view 4 >out", [["pr", "view", "4"]]),
    ],
)
def test_file_descriptors_are_not_arguments(
    command: str, argument_lists: list[list[str]]
) -> None:
    assert gh_argument_lists(command) == argument_lists


@pytest.mark.parametrize("body", ['""', '"a; b"', "'a && b'", '"a\nb"'])
def test_quoted_operators_stay_inside_the_gh_call(body: str) -> None:
    command = f"gh pr comment 1 --body {body} -R o/r"
    assert gh_argument_lists(command)[0][-2:] == ["-R", "o/r"]
