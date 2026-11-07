import pytest
from gh_arguments import gh_arguments
from gh_requests import gh_request
from pull_request_writes import denial, mcp_tools_denial, pull_request_write_tools


def suggested_tools(*arguments: str) -> list[str]:
    request = gh_request(gh_arguments(arguments))
    assert request is not None
    return pull_request_write_tools(request)


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
        (["pr", "comment", "1"], "add_issue_comment"),
        (["pr", "comment", "1", "--edit-last", "-b", "x"], "update_issue_comment"),
    ],
)
def test_denies_pull_request_writes_from_the_cli(
    arguments: list[str], tool: str
) -> None:
    assert suggested_tools(*arguments) == [tool]


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
        ("POST", "repos/o/r/pulls/1/ccr/comments/2/resolve", "resolve_review_thread"),
        (
            "POST",
            "repos/o/r/pulls/1/ccr/comments/2/unresolve",
            "unresolve_review_thread",
        ),
    ],
)
def test_denies_pull_request_writes_through_rest(
    method: str, endpoint: str, tool: str
) -> None:
    assert suggested_tools("api", "-X", method, endpoint) == [tool]


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
    ],
)
def test_denies_pull_request_writes_however_gh_is_called(
    arguments: list[str], tool: str
) -> None:
    assert suggested_tools(*arguments) == [tool]


@pytest.mark.parametrize(
    "arguments",
    [
        ["api", "repos/o/r/pulls/1/comments", "-F", "in_reply_to=5", "-f", "body=x"],
        ["api", "repos/o/r/pulls/1/comments", "-f", "in_reply_to[x]=5"],
    ],
)
def test_names_the_reply_tool_for_a_review_comment_reply(arguments: list[str]) -> None:
    assert suggested_tools(*arguments) == ["add_reply_to_pull_request_comment"]


@pytest.mark.parametrize("body", ["reply.json", "-"])
def test_names_both_comment_tools_for_a_review_comment_body_it_cannot_see(
    body: str,
) -> None:
    assert suggested_tools("api", "repos/o/r/pulls/1/comments", "--input", body) == [
        "add_reply_to_pull_request_comment",
        "add_comment_to_pending_review",
    ]


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
        ["pr", "update-branch", "1", "--rebase"],
        ["pr", "create", "--help"],
        ["pr", "create", "-h"],
        ["pr", "comment", "--help"],
        ["pr", "merge", "1", "--help"],
        ["pr", "review", "--help"],
        ["pr", "ready", "--help"],
        ["pr", "close", "--help"],
        ["pr", "reopen", "--help"],
        ["pr", "update-branch", "--help"],
        ["api", "-X", "POST", "repos/o/r/pulls", "--help"],
        ["pr", "comment", "1", "--attach", "shot.png"],
        ["pr", "comment", "1", "--body", "x", "--attach=shot.png"],
        ["pr", "edit", "1", "--body", "x", "--attach", "shot.png"],
        ["pr", "create", "--fill", "--attach", "shot.png"],
        ["pr", "revert", "1"],
        ["api", "repos/o/r/pulls"],
        ["api", "repos/o/r/pulls/1/ccr/review_threads"],
        ["api", "-X", "PATCH", "repos/o/r/pulls/comments/5", "-f", "body=x"],
        ["api", "-X", "DELETE", "repos/o/r/pulls/comments/5"],
        ["api", "-X", "PUT", "repos/o/r/pulls/1/reviews/2", "-f", "body=x"],
        ["api", "-X", "PUT", "repos/o/r/pulls/1/reviews/2/dismissals"],
        ["api", "-X", "DELETE", "repos/o/r/pulls/1/requested_reviewers"],
        ["api", "-X", "DELETE", "repos/o/r/pulls/comments/5/reactions/7"],
        ["api", "repos/o/r/pulls/comments/2/reactions", "-f", "content=+1"],
        ["api", "graphql", "-f", "query=mutation { mergePullRequest }"],
        ["api", "repos/o/r/issues/1/labels", "-f", "labels[]=x"],
        ["api", "-X", "PUT", "repos/o/r/issues/1/lock"],
        ["api", "repos/o/r/issues", "-f", "title=x"],
        ["api", "repositories/123/issues", "-f", "title=x"],
        ["api", "-X", "PATCH", "repos/o/r/issues/7", "-f", "state=closed"],
        ["api", "-X", "PATCH", "repos/o/r/issues/comments/9", "-f", "body=x"],
        ["api", "repos/o/r/issues/comments/9/reactions", "-f", "content=+1"],
        ["api", "repos/o/r/issues/7/reactions", "-f", "content=+1"],
        ["api", "search/code?q=mergePullRequest"],
        ["api", "repos/o/r/issues/1/comments", "-f", "body=createPullRequest fails"],
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
        ["api", "repos/o/r/issues", "-f", "body=see /pulls/1"],
        ["api", "-H", "Accept: x/pulls", "repos/o/r/issues", "-f", "title=x"],
    ],
)
def test_lets_other_commands_through(arguments: list[str]) -> None:
    assert denial(arguments) is None


def test_names_the_tool_and_the_way_out() -> None:
    assert denial(["pr", "merge", "1"]) == (
        "gh: use the GitHub MCP tool merge_pull_request for this."
        " The agent that opened a pull request, or its parent, manages it."
        " If you lack merge_pull_request, ask your parent agent to do it."
        " Run gh with ALLOW_GH_PULL_REQUEST_WRITE=1 only when the user asks."
    )


def test_joins_several_tools_with_or() -> None:
    message = mcp_tools_denial(["first_tool", "second_tool"])
    assert "use the GitHub MCP tool first_tool or second_tool for this." in message
    assert "If you lack first_tool or second_tool, ask" in message


@pytest.mark.parametrize(
    ("endpoint", "tool"),
    [
        ("repos/o/r//pulls/1/merge", "merge_pull_request"),
        ("repos/o/r/./pulls/1/merge", "merge_pull_request"),
        ("repos/o/r/pulls//1/merge", "merge_pull_request"),
        ("repos/o/r/pull%73/1/merge", "merge_pull_request"),
        ("repos/o/r/pulls%2F1%2Fmerge", "merge_pull_request"),
        ("repos/o/r/issues/../pulls/1/merge", "merge_pull_request"),
        ("repos//o/r/pulls/1/merge", "merge_pull_request"),
        ("/repositories/123//pulls/1/./merge", "merge_pull_request"),
        ("repos/o/r/pulls/1/update%2Dbranch", "update_pull_request_branch"),
    ],
)
def test_denies_pull_request_writes_on_paths_that_name_the_same_route(
    endpoint: str, tool: str
) -> None:
    assert suggested_tools("api", "-X", "PUT", endpoint) == [tool]


@pytest.mark.parametrize(
    ("arguments", "tool"),
    [
        (["pr", "merge", "1", "--subject", "-h"], "merge_pull_request"),
        (["pr", "merge", "1", "-t", "--help"], "merge_pull_request"),
        (["pr", "merge", "1", "--body", "--attach"], "merge_pull_request"),
        (
            ["api", "-X", "PUT", "repos/o/r/pulls/1/merge", "-f", "-h=1"],
            "merge_pull_request",
        ),
        (["pr", "update-branch", "1", "--rebase=false"], "update_pull_request_branch"),
        (["pr", "merge", "1", "--auto=false"], "merge_pull_request"),
        (["pr", "merge", "1", "--auto", "--auto=0"], "merge_pull_request"),
        (["pr", "comment", "1", "--delete-last=false", "-b", "x"], "add_issue_comment"),
        (["pr", "merge", "-sd", "1"], "merge_pull_request"),
    ],
)
def test_reads_flag_values_as_values(arguments: list[str], tool: str) -> None:
    assert suggested_tools(*arguments) == [tool]


@pytest.mark.parametrize(
    "arguments",
    [
        ["pr", "edit", "1", "--add-label", "-tx"],
        ["pr", "edit", "1", "--add-label", "--title"],
        ["pr", "update-branch", "1", "--rebase=true"],
        ["pr", "merge", "1", "-h"],
        ["pr", "merge", "1", "-sh"],
    ],
)
def test_reads_flags_only_where_gh_reads_them(arguments: list[str]) -> None:
    assert denial(arguments) is None


def test_names_both_tools_when_the_last_comment_may_be_created() -> None:
    arguments = ["pr", "comment", "1", "--edit-last", "--create-if-none", "-b", "x"]
    assert suggested_tools(*arguments) == ["update_issue_comment", "add_issue_comment"]
