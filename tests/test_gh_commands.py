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


@pytest.mark.parametrize(
    ("command", "argument_lists"),
    [
        (
            "gh pr view 1 # gh pr close 1\ngh pr view 2",
            [["pr", "view", "1"], ["pr", "view", "2"]],
        ),
        ("# gh pr close 1\ngh pr view 2", [["pr", "view", "2"]]),
        ("gh pr view 1;# x\ngh pr view 2", [["pr", "view", "1"], ["pr", "view", "2"]]),
        ("gh pr comment 1 --body a#b", [["pr", "comment", "1", "--body", "a#b"]]),
        ('gh pr comment 1 --body "# x"', [["pr", "comment", "1", "--body", "# x"]]),
        ("gh pr comment 1 --body \\#x", [["pr", "comment", "1", "--body", "#x"]]),
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
        (
            "gh pr view 1 # note \\\ngh pr close 2",
            [["pr", "view", "1"], ["pr", "close", "2"]],
        ),
        (
            "gh pr comment 1 --body $'it\\'s # done' ; gh pr close 2",
            [["pr", "comment", "1", "--body", "it's # done"], ["pr", "close", "2"]],
        ),
        (
            'gh pr comment 1 --body "a \\"#\\" \\\nb" -R o/r',
            [["pr", "comment", "1", "--body", 'a "#" b', "-R", "o/r"]],
        ),
        ("gh pr view 1 \\\n  -R o/r", [["pr", "view", "1", "-R", "o/r"]]),
        (
            'gh pr comment 1 --body "a 2>b" -R o/r',
            [["pr", "comment", "1", "--body", "a 2>b", "-R", "o/r"]],
        ),
        (
            "gh pr view 1 2>/dev/null; gh pr view 2",
            [["pr", "view", "1"], ["pr", "view", "2"]],
        ),
    ],
)
def test_quotes_and_line_continuations_follow_bash(command, argument_lists):
    assert gh_argument_lists(command) == argument_lists


@pytest.mark.parametrize("body", ['""', '";"', "'&&'", '"|"', r"\;", '"\n"'])
def test_quoted_operators_stay_inside_the_gh_call(body):
    command = f"gh pr comment 1 --body {body} -R o/r"
    assert gh_argument_lists(command)[0][-2:] == ["-R", "o/r"]


@pytest.mark.parametrize(
    ("command", "argument_lists"),
    [
        (
            "gh pr view 1 <<'EOF'\ndoesn't\nEOF\ngh pr view 2",
            [["pr", "view", "1"], ["pr", "view", "2"]],
        ),
        (
            "gh pr view 1 <<EOF\ndoesn't\nEOF\ngh pr view 2",
            [["pr", "view", "1"], ["pr", "view", "2"]],
        ),
        ("cat <<EOF\ngh pr close 9\nEOF", []),
        ("cat <<-EOF\n\tgh pr close 9\n\tEOF\ngh pr view 2", [["pr", "view", "2"]]),
        ("cat <<EOF | gh pr view 1\ngh pr close 9\nEOF", [["pr", "view", "1"]]),
        (
            "cat <<A <<'B'\ngh pr close 1\nA\ngh pr close 2\nB\ngh pr view 3",
            [["pr", "view", "3"]],
        ),
        ("cat <<< x\ngh pr view 1", [["pr", "view", "1"]]),
        ("cat <<EOF; gh pr view 1\nbody\nEOF", [["pr", "view", "1"]]),
        (
            'x=$(cat <<EOF\nbody\nEOF)\ngh pr create --body "$x"',
            [["pr", "create", "--body", "$x"]],
        ),
        (
            "x=$(cat <<-EOF\n\tgh pr close 9\n\tEOF\n)\ngh pr view 2",
            [["pr", "view", "2"]],
        ),
        ("echo $((1<<2))\ngh pr view 2", [["pr", "view", "2"]]),
        ("((x = 1 << 2))\ngh pr view 2", [["pr", "view", "2"]]),
        (
            "case $x in a) gh pr view 1;; esac\ncat <<E\nE) item's\nE\ngh pr view 2",
            [["pr", "view", "1"], ["pr", "view", "2"]],
        ),
    ],
)
def test_heredoc_bodies_are_not_commands(command, argument_lists):
    assert gh_argument_lists(command) == argument_lists


@pytest.mark.parametrize(
    "command", ['gh pr create --title "unterminated', "((gh pr create) | wc)"]
)
def test_calls_behind_broken_quotes_or_nested_subshells_are_found(command):
    [arguments] = gh_argument_lists(command)
    assert gh_pr_call(arguments).creates_a_pull_request()


@pytest.mark.parametrize(
    "command",
    [
        "bash -lc 'gh pr view 1' && sh -c \"gh pr view 1\"",
        ["bash", "-lc", "gh pr view 1"],
        ["gh", "pr", "view", "1"],
    ],
)
def test_calls_inside_shell_command_strings_are_found(command):
    assert set(map(tuple, gh_argument_lists(command))) == {("pr", "view", "1")}


@pytest.mark.parametrize(
    ("command", "argument_lists"),
    [
        ("cat <<EOF\n$(gh pr view 1)\nEOF", [["pr", "view", "1"]]),
        ("cat <<'EOF'\n$(gh pr view 1)\nEOF", []),
    ],
)
def test_substitutions_run_only_in_unquoted_heredocs(command, argument_lists):
    assert gh_argument_lists(command) == argument_lists
