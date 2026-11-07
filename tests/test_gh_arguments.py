import pytest
from gh_arguments import GhArguments, Option, gh_arguments


@pytest.mark.parametrize(
    ("arguments", "parsed"),
    [
        (
            ["pr", "--body", "merge", "edit", "1"],
            GhArguments(("pr", "edit"), ("1",), (Option("body", "merge"),)),
        ),
        (
            ["-R", "o/r", "pr", "merge", "-st", "x", "1"],
            GhArguments(
                ("pr", "merge"),
                ("1",),
                (Option("repo", "o/r"), Option("squash", True), Option("subject", "x")),
            ),
        ),
        (
            ["api", "-iX=put", "--", "-f", "x"],
            GhArguments(
                ("api",),
                ("-f", "x"),
                (Option("include", True), Option("method", "put")),
            ),
        ),
        (["--", "pr", "merge"], GhArguments((), ("pr", "merge"), ())),
        (
            ["pr", "update-branch", "--rebase=f"],
            GhArguments(("pr", "update-branch"), (), (Option("rebase", False),)),
        ),
        (
            ["pr", "view", "--json", "number", "5"],
            GhArguments(("pr", "view"), ("5",), (Option("json", "number"),)),
        ),
    ],
)
def test_parses_flags_by_what_they_take(
    arguments: list[str], parsed: GhArguments
) -> None:
    assert gh_arguments(arguments) == parsed


def test_last_switch_value_wins() -> None:
    parsed = gh_arguments(["pr", "merge", "--auto", "--auto=false", "--squash"])
    assert parsed.given_flags() == {"squash"}
