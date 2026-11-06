import re
import subprocess

import pytest
from conftest import FAKE_GH, ShimRun, ShimRunner

SUGGESTED_TOOL = re.compile(r"use the GitHub MCP tool (\w+) ")


@pytest.fixture
def run_gh_in_cloud(shim_runner: ShimRunner) -> ShimRun:
    return shim_runner("gh", FAKE_GH, CLAUDE_CODE_REMOTE="true")


@pytest.fixture
def run_gh_elsewhere(shim_runner: ShimRunner) -> ShimRun:
    return shim_runner("gh", FAKE_GH)


def suggested_tool(result: subprocess.CompletedProcess[str]) -> str:
    assert result.returncode == 1
    found = SUGGESTED_TOOL.search(result.stderr)
    assert found, result.stderr
    return found[1]


def mutation(name: str) -> str:
    return f"mutation {{ {name}(input: {{}}) {{ clientMutationId }} }}"


WRITES_ON_EVERY_PATH = [
    ["pr", "merge", "1"],
    ["api", "-X", "POST", "repos/o/r/pulls/1/reviews"],
    ["api", "graphql", "-f", f"query={mutation('resolveReviewThread')}"],
    ["api", "graphql", "--input", "-"],
]


def assert_ran(result: subprocess.CompletedProcess[str], arguments: list[str]) -> None:
    assert result.returncode == 0, result.stderr
    assert result.stdout == f"ran {' '.join(arguments)}\n"


@pytest.mark.parametrize(
    ("arguments", "tool"),
    [
        (["pr", "create", "--fill"], "create_pull_request"),
        (["pr", "new", "--fill"], "create_pull_request"),
        (["pr", "edit", "1", "--title", "x"], "update_pull_request"),
        (["pr", "edit", "1", "-t", "x"], "update_pull_request"),
        (["pr", "edit", "1", "--body", "x"], "update_pull_request"),
        (["pr", "edit", "1", "-b", "x"], "update_pull_request"),
        (["pr", "edit", "1", "--body-file", "body.md"], "update_pull_request"),
        (["pr", "edit", "1", "-F", "body.md"], "update_pull_request"),
        (["pr", "edit", "1", "--base", "main"], "update_pull_request"),
        (["pr", "edit", "1", "-B", "main"], "update_pull_request"),
        (["pr", "edit", "1", "--add-reviewer", "x"], "update_pull_request"),
        (["pr", "ready", "1"], "update_pull_request"),
        (["pr", "ready", "1", "--undo"], "update_pull_request"),
        (["pr", "close", "1"], "update_pull_request"),
        (["pr", "reopen", "1"], "update_pull_request"),
        (["pr", "merge", "1", "--auto"], "enable_pr_auto_merge"),
        (["pr", "merge", "1", "--disable-auto"], "disable_pr_auto_merge"),
        (["pr", "merge", "1"], "merge_pull_request"),
        (["pr", "update-branch", "1"], "update_pull_request_branch"),
        (["pr", "review", "1", "--approve"], "pull_request_review_write"),
        (["pr", "comment", "1", "--body", "x"], "add_issue_comment"),
        (["pr", "comment", "1", "-b", "x"], "add_issue_comment"),
        (["pr", "comment", "1", "--body-file", "x.md"], "add_issue_comment"),
        (["pr", "comment", "1", "-F", "x.md"], "add_issue_comment"),
        (["pr", "comment", "1", "--edit-last", "-b", "x"], "update_issue_comment"),
    ],
)
def test_denies_pull_request_writes_from_the_cli(
    run_gh_in_cloud: ShimRun, arguments: list[str], tool: str
) -> None:
    assert suggested_tool(run_gh_in_cloud(*arguments)) == tool


@pytest.mark.parametrize(
    ("method", "endpoint", "tool"),
    [
        ("POST", "repos/o/r/pulls", "create_pull_request"),
        ("PATCH", "repos/o/r/pulls/1", "update_pull_request"),
        ("POST", "repos/o/r/pulls/1/requested_reviewers", "update_pull_request"),
        ("POST", "repos/o/r/pulls/1/ccr/ready_for_review", "update_pull_request"),
        ("POST", "repos/o/r/pulls/1/ccr/convert_to_draft", "update_pull_request"),
        ("PUT", "repos/o/r/pulls/1/ccr/auto_merge", "enable_pr_auto_merge"),
        ("DELETE", "repos/o/r/pulls/1/ccr/auto_merge", "disable_pr_auto_merge"),
        ("PUT", "repos/o/r/pulls/1/merge", "merge_pull_request"),
        ("PUT", "repos/o/r/pulls/1/update-branch", "update_pull_request_branch"),
        ("POST", "repos/o/r/pulls/1/reviews", "pull_request_review_write"),
        ("POST", "repos/o/r/pulls/1/reviews/2/events", "pull_request_review_write"),
        ("DELETE", "repos/o/r/pulls/1/reviews/2", "pull_request_review_write"),
        ("POST", "repos/o/r/pulls/1/comments", "add_comment_to_pending_review"),
        (
            "POST",
            "repos/o/r/pulls/1/comments/2/replies",
            "add_reply_to_pull_request_comment",
        ),
        (
            "POST",
            "repos/o/r/pulls/comments/2/reactions",
            "add_reply_to_pull_request_comment",
        ),
        ("POST", "repos/o/r/pulls/1/ccr/comments/2/resolve", "resolve_review_thread"),
        (
            "POST",
            "repos/o/r/pulls/1/ccr/comments/2/unresolve",
            "unresolve_review_thread",
        ),
    ],
)
def test_denies_pull_request_writes_through_rest(
    run_gh_in_cloud: ShimRun, method: str, endpoint: str, tool: str
) -> None:
    assert suggested_tool(run_gh_in_cloud("api", "-X", method, endpoint)) == tool


@pytest.mark.parametrize(
    ("name", "tool"),
    [
        ("createPullRequest", "create_pull_request"),
        ("updatePullRequest", "update_pull_request"),
        ("closePullRequest", "update_pull_request"),
        ("reopenPullRequest", "update_pull_request"),
        ("markPullRequestReadyForReview", "update_pull_request"),
        ("convertPullRequestToDraft", "update_pull_request"),
        ("requestReviews", "update_pull_request"),
        ("requestReviewsByLogin", "update_pull_request"),
        ("enablePullRequestAutoMerge", "enable_pr_auto_merge"),
        ("disablePullRequestAutoMerge", "disable_pr_auto_merge"),
        ("mergePullRequest", "merge_pull_request"),
        ("updatePullRequestBranch", "update_pull_request_branch"),
        ("addPullRequestReview", "pull_request_review_write"),
        ("submitPullRequestReview", "pull_request_review_write"),
        ("deletePullRequestReview", "pull_request_review_write"),
        ("addPullRequestReviewThread", "add_comment_to_pending_review"),
        ("addPullRequestReviewComment", "add_comment_to_pending_review"),
        ("addPullRequestReviewThreadReply", "add_reply_to_pull_request_comment"),
        ("resolveReviewThread", "resolve_review_thread"),
        ("unresolveReviewThread", "unresolve_review_thread"),
    ],
)
def test_denies_pull_request_writes_through_graphql(
    run_gh_in_cloud: ShimRun, name: str, tool: str
) -> None:
    result = run_gh_in_cloud("api", "graphql", "-f", f"query={mutation(name)}")
    assert suggested_tool(result) == tool


@pytest.mark.parametrize(
    ("arguments", "tool"),
    [
        (["api", "-Xpost", "repos/o/r/pulls"], "create_pull_request"),
        (["api", "--method=PUT", "repos/o/r/pulls/1/merge"], "merge_pull_request"),
        (["api", "repos/o/r/pulls", "-f", "title=x"], "create_pull_request"),
        (["api", "repos/o/r/pulls", "--input=body.json"], "create_pull_request"),
        (["api", "repos/o/r/pulls", "-ftitle=x"], "create_pull_request"),
        (["api", "/repos/o/r/pulls", "-f", "title=x"], "create_pull_request"),
        (["api", "repos/{owner}/{repo}/pulls", "-f", "x=y"], "create_pull_request"),
        (["api", "repos/o/r/pulls?x=1", "-f", "title=x"], "create_pull_request"),
        (["api", "-X", "PUT", "repos/o/r/pulls/1/merge/"], "merge_pull_request"),
        (
            ["api", "-X", "PUT", "https://api.github.com/repos/o/r/pulls/1/merge"],
            "merge_pull_request",
        ),
        (
            ["api", "repos/o/r/pulls/1/comments/2/replies", "-f", "body=x"],
            "add_reply_to_pull_request_comment",
        ),
        (
            ["api", "-X", "POST", "repos/o/r/pulls/1/reviews", "-f", "event=COMMENT"],
            "pull_request_review_write",
        ),
        (["pr", "-R", "o/r", "merge", "1"], "merge_pull_request"),
        (["pr", "--repo=o/r", "create"], "create_pull_request"),
        (["-R", "o/r", "pr", "create", "--fill"], "create_pull_request"),
        (["--repo", "o/r", "pr", "merge", "1"], "merge_pull_request"),
        (["--repo=o/r", "pr", "edit", "1", "--body", "x"], "update_pull_request"),
        (["-Ro/r", "pr", "merge", "1"], "merge_pull_request"),
        (["pr", "--body", "x", "merge", "1"], "merge_pull_request"),
        (["pr", "", "merge", "1"], "merge_pull_request"),
        (["pr", "edit", "1", "--title=x"], "update_pull_request"),
        (["pr", "edit", "1", "-tx"], "update_pull_request"),
        (["pr", "edit", "1", "--add-label", "x", "-B", "main"], "update_pull_request"),
        (["pr", "merge", "1", "--auto=true"], "enable_pr_auto_merge"),
        (["pr", "merge", "--auto", "1", "--squash"], "enable_pr_auto_merge"),
        (["pr", "comment", "1", "--body=x"], "add_issue_comment"),
        (
            ["pr", "comment", "1", "--edit-last", "--create-if-none", "-b", "x"],
            "update_issue_comment",
        ),
        (
            ["api", "-X", "PUT", "repositories/123/pulls/1/merge"],
            "merge_pull_request",
        ),
        (["api", "repositories/123/pulls", "-f", "title=x"], "create_pull_request"),
        (
            ["--jq", ".url", "api", "-X", "POST", "repos/o/r/pulls"],
            "create_pull_request",
        ),
        (
            ["api", "--paginate", "repos/o/r/pulls", "-f", "title=x"],
            "create_pull_request",
        ),
        (
            ["api", "-X", "POST", "-f", "title=x", "--", "repos/o/r/pulls"],
            "create_pull_request",
        ),
        (
            ["api", "-iX", "POST", "repos/o/r/pulls", "-f", "title=x"],
            "create_pull_request",
        ),
        (["api", "-iXPOST", "repos/o/r/pulls"], "create_pull_request"),
        (["api", "-if", "title=x", "repos/o/r/pulls"], "create_pull_request"),
        (
            ["api", "--some-new-switch", "repos/o/r/pulls", "-f", "title=x"],
            "create_pull_request",
        ),
        (["api", "-X=PUT", "repos/o/r/pulls/1/merge"], "merge_pull_request"),
        (["api", "-iX=PUT", "repos/o/r/pulls/1/merge"], "merge_pull_request"),
        (["api", "-i=t", "repos/o/r/pulls", "-f", "title=x"], "create_pull_request"),
        (
            ["api", "/graphql", "-f", f"query={mutation('createPullRequest')}"],
            "create_pull_request",
        ),
        (
            [
                "api",
                "https://api.github.com/graphql",
                "-f",
                f"query={mutation('mergePullRequest')}",
            ],
            "merge_pull_request",
        ),
        (
            ["api", "graphql?x=1", "-f", f"query={mutation('mergePullRequest')}"],
            "merge_pull_request",
        ),
        (
            ["api", "graphql#x", "-f", f"query={mutation('mergePullRequest')}"],
            "merge_pull_request",
        ),
        (
            ["api", "/graphql/", "-f", f"query={mutation('mergePullRequest')}"],
            "merge_pull_request",
        ),
        (
            ["api", "graphql", "--raw-field", f"query={mutation('mergePullRequest')}"],
            "merge_pull_request",
        ),
        (
            ["api", "graphql", "-F", f"query={mutation('closePullRequest')}"],
            "update_pull_request",
        ),
        (
            ["api", "graphql", "-f", "query=mutation { m: mergePullRequest(x: 1) }"],
            "merge_pull_request",
        ),
    ],
)
def test_denies_pull_request_writes_however_gh_is_called(
    run_gh_in_cloud: ShimRun, arguments: list[str], tool: str
) -> None:
    assert suggested_tool(run_gh_in_cloud(*arguments)) == tool


@pytest.mark.parametrize(
    "arguments",
    [
        ["api", "graphql", "-F", "query=@query.graphql"],
        ["api", "graphql", "-F=query=@query.graphql"],
        ["api", "graphql", "--field", "query=@query.graphql"],
        ["api", "graphql", "-F", "query=@/dev/stdin"],
        ["api", "graphql", "-F", "query=@-"],
        ["api", "graphql", "--input", "body.json"],
        ["api", "graphql", "--input=body.json"],
        ["api", "graphql", "--input", "-"],
    ],
)
def test_denies_a_graphql_query_from_a_file_or_standard_input(
    run_gh_in_cloud: ShimRun, arguments: list[str]
) -> None:
    result = run_gh_in_cloud(*arguments)
    assert result.returncode == 1
    assert "pass the GraphQL query inline" in result.stderr


@pytest.mark.parametrize(
    "arguments",
    [
        ["pr", "view", "1"],
        ["pr", "list"],
        ["pr", "checkout", "1"],
        ["pr", "-R", "o/r", "view", "1"],
        ["-R", "o/r", "pr", "view", "1"],
        ["pr", "edit", "1", "--add-label", "x"],
        ["pr", "edit", "1", "--remove-label", "x"],
        ["pr", "edit", "1", "--add-assignee", "x"],
        ["pr", "edit", "1", "--remove-assignee", "x"],
        ["pr", "edit", "1", "--add-label", "x", "--add-assignee", "y"],
        ["pr", "edit", "1", "--milestone", "x"],
        ["pr", "edit", "1", "--remove-milestone"],
        ["pr", "edit", "1", "--add-project", "x"],
        ["pr", "edit", "1", "--remove-project", "x"],
        ["pr", "edit", "1", "--remove-reviewer", "x"],
        ["pr", "lock", "1"],
        ["pr", "unlock", "1"],
        ["pr", "comment", "1", "--delete-last"],
        ["pr", "revert", "1"],
        ["api", "repos/o/r/pulls"],
        ["api", "repos/o/r/pulls/1/ccr/review_threads"],
        ["api", "-X", "PATCH", "repos/o/r/pulls/comments/5", "-f", "body=x"],
        ["api", "-X", "DELETE", "repos/o/r/pulls/comments/5"],
        ["api", "-X", "PUT", "repos/o/r/pulls/1/reviews/2", "-f", "body=x"],
        ["api", "-X", "PUT", "repos/o/r/pulls/1/reviews/2/dismissals"],
        ["api", "-X", "DELETE", "repos/o/r/pulls/1/requested_reviewers"],
        ["api", "-X", "DELETE", "repos/o/r/pulls/comments/5/reactions/7"],
        ["api", "repos/o/r/issues/1/labels", "-f", "labels[]=x"],
        ["api", "-X", "PUT", "repos/o/r/issues/1/lock"],
        ["api", "repos/o/r/issues", "-f", "title=x"],
        ["api", "repositories/123/issues", "-f", "title=x"],
        ["api", "search/code?q=mergePullRequest"],
        ["api", "repos/o/r/issues/1/comments", "-f", "body=createPullRequest fails"],
        ["api", "graphql", "-f", "query=query { viewer { login } }"],
        ["api", "graphql", "-f", f"query={mutation('updatePullRequestReview')}"],
        ["api", "graphql", "-f", f"query={mutation('updatePullRequestReviewComment')}"],
        ["api", "graphql", "-f", f"query={mutation('deletePullRequestReviewComment')}"],
        ["api", "graphql", "-f", f"query={mutation('dismissPullRequestReview')}"],
        ["api", "graphql", "-f", f"query={mutation('addLabelsToLabelable')}"],
        ["api", "graphql", "-f", f"query={mutation('addAssigneesToAssignable')}"],
        ["api", "graphql", "-f", f"query={mutation('lockLockable')}"],
        ["api", "graphql", "-f", f"query={mutation('enqueuePullRequest')}"],
        ["api", "graphql", "-f", f"query={mutation('revertPullRequest')}"],
        [
            "api",
            "graphql",
            "-f",
            "query=query($q: String!) { search(query: $q) { issueCount } }",
            "-f",
            "q=mergePullRequest",
        ],
        ["issue", "create", "--title", "pr merge"],
        [],
        [
            "api",
            "-q",
            "graphql",
            "repos/o/r/issues/1/comments",
            "-f",
            "body=mergePullRequest",
        ],
        ["api", "graphql", "-f", "query=@mutation.graphql"],
        ["api", "repos/o/r/issues", "-f", "body=see /pulls/1"],
        ["api", "-H", "Accept: x/pulls", "repos/o/r/issues", "-f", "title=x"],
    ],
)
def test_runs_other_commands(run_gh_in_cloud: ShimRun, arguments: list[str]) -> None:
    assert_ran(run_gh_in_cloud(*arguments), arguments)


@pytest.mark.parametrize("arguments", WRITES_ON_EVERY_PATH)
def test_runs_pull_request_writes_on_request(
    run_gh_in_cloud: ShimRun, arguments: list[str]
) -> None:
    assert_ran(run_gh_in_cloud(*arguments, ALLOW_GH_PULL_REQUEST_WRITE="1"), arguments)


@pytest.mark.parametrize("arguments", WRITES_ON_EVERY_PATH)
def test_runs_pull_request_writes_outside_claude_cloud(
    run_gh_elsewhere: ShimRun, arguments: list[str]
) -> None:
    assert_ran(run_gh_elsewhere(*arguments), arguments)


def test_runs_pull_request_writes_when_the_session_is_not_remote(
    run_gh_elsewhere: ShimRun,
) -> None:
    result = run_gh_elsewhere("pr", "merge", "1", CLAUDE_CODE_REMOTE="false")
    assert_ran(result, ["pr", "merge", "1"])
