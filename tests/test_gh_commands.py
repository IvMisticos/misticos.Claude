import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hooks"))

import pytest
from gh_commands import GhPrCall, gh_pr_call
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
