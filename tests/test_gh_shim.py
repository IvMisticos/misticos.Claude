import pytest
from conftest import FAKE_GH


@pytest.fixture
def run_gh(shim_runner):
    return shim_runner("gh", FAKE_GH)


@pytest.mark.parametrize(
    "arguments",
    [
        ["pr", "create", "--fill"],
        ["pr", "merge", "1"],
        ["api", "-X", "POST", "repos/o/r/pulls"],
        ["api", "-Xpost", "repos/o/r/pulls"],
        ["api", "--method=PUT", "repos/o/r/pulls/1/merge"],
        ["api", "repos/o/r/pulls", "-f", "title=x"],
        ["api", "repos/o/r/pulls", "--input=body.json"],
        ["api", "repos/o/r/pulls", "-ftitle=x"],
        ["pr", "-R", "o/r", "merge", "1"],
        ["pr", "--repo=o/r", "create"],
        ["pr", "new", "--fill"],
        ["api", "graphql", "-f", "query=mutation { mergePullRequest(input: {}) }"],
        ["pr", "edit", "1", "--body", "x"],
        ["api", "-X", "PATCH", "repos/o/r/pulls/1", "-f", "body=x"],
        ["api", "graphql", "-f", "query=mutation { enqueuePullRequest(input: {}) }"],
        ["api", "/graphql", "-f", "query=mutation { createPullRequest(input: {}) }"],
        [
            "api",
            "https://api.github.com/graphql",
            "-f",
            "query=mutation { mergePullRequest(input: {}) }",
        ],
        [
            "api",
            "graphql",
            "-f",
            "query=mutation { enablePullRequestAutoMerge(input: {}) }",
        ],
    ],
)
def test_denies_pull_request_writes(run_gh, arguments):
    result = run_gh(*arguments)
    assert result.returncode == 1
    assert "GitHub MCP tools" in result.stderr


@pytest.mark.parametrize(
    "arguments",
    [
        ["pr", "view", "1"],
        ["pr", "list"],
        ["pr", "-R", "o/r", "view", "1"],
        ["api", "repos/o/r/pulls"],
        ["api", "repos/o/r/issues", "-f", "title=x"],
        ["api", "search/code?q=mergePullRequest"],
        ["api", "repos/o/r/issues/1/comments", "-f", "body=createPullRequest fails"],
        ["api", "graphql", "-f", "query=query { viewer { login } }"],
        ["issue", "create", "--title", "pr merge"],
    ],
)
def test_runs_other_commands(run_gh, arguments):
    result = run_gh(*arguments)
    assert result.returncode == 0
    assert result.stdout == f"ran {' '.join(arguments)}\n"


def test_runs_pull_request_writes_on_request(run_gh):
    result = run_gh("pr", "merge", "1", ALLOW_GH_PULL_REQUEST_WRITE="1")
    assert result.stdout == "ran pr merge 1\n"
