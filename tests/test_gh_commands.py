import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hooks"))

import pytest
from gh_commands import GhPrCall, gh_api_words, gh_pr_call
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
    "arguments",
    [
        ["pr", "--json", "number", "view", "5"],
        ["--jq", ".number", "pr", "view", "5"],
        ["-R", "o/r", "pr", "-q", ".number", "view", "5"],
    ],
)
def test_flag_values_before_the_subcommand_are_skipped(arguments):
    call = gh_pr_call(arguments)
    assert (call.subcommand, call.target) == ("view", "5")


def test_flag_values_before_api_are_skipped():
    words = gh_api_words(["--jq", ".url", "api", "repos/o/r/pulls/1"])
    assert words == ["repos/o/r/pulls/1"]
