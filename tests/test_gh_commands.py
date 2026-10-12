import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hooks"))

from gh_commands import GhPrCall, gh_pr_call


def test_missing_target_and_repo_are_none():
    assert gh_pr_call(["pr", "list"]) == GhPrCall("list", None, None)


def test_repo_flag_without_value_leaves_repo_none():
    assert gh_pr_call(["pr", "view", "1", "-R"]) == GhPrCall("view", "1", None)
