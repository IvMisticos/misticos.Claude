import sys
from collections.abc import Sequence
from typing import NamedTuple

from gh_arguments import CREATE_SUBCOMMANDS, gh_arguments
from gh_requests import GhRequest, PrCommand, RestRequest, gh_request

ANY_SEGMENT = "*"
WRITE_METHODS = frozenset({"POST", "PUT", "PATCH"})
DELETE_METHOD = frozenset({"DELETE"})
UNCHECKED_FLAGS = frozenset({"help", "attach"})


def resource_matches(pattern: str, resource: Sequence[str]) -> bool:
    expected_segments = pattern.split("/")
    if len(resource) != len(expected_segments):
        return False
    return all(
        expected in (segment, ANY_SEGMENT)
        for expected, segment in zip(expected_segments, resource, strict=True)
    )


class PrCommandForm(NamedTuple):
    subcommands: frozenset[str]
    any_flag: frozenset[str] = frozenset()
    absent_flags: frozenset[str] = frozenset()

    def matches(self, request: GhRequest) -> bool:
        if not isinstance(request, PrCommand):
            return False
        if request.subcommand not in self.subcommands:
            return False
        if self.any_flag and not self.any_flag & request.flags:
            return False
        return not self.absent_flags & request.flags


class RestForm(NamedTuple):
    methods: frozenset[str]
    resource: str
    field: str | None = None
    reads_input: bool = False

    def matches(self, request: GhRequest) -> bool:
        if not isinstance(request, RestRequest) or request.method not in self.methods:
            return False
        if not resource_matches(self.resource, request.resource):
            return False
        if self.field is not None and self.field not in request.field_names:
            return False
        return request.reads_input or not self.reads_input


class PullRequestWrite(NamedTuple):
    tool: str
    form: PrCommandForm | RestForm
    alternative_tool: str | None = None

    def tools(self) -> list[str]:
        return [tool for tool in (self.tool, self.alternative_tool) if tool]


PULL_REQUEST_WRITES = (
    PullRequestWrite("create_pull_request", PrCommandForm(CREATE_SUBCOMMANDS)),
    PullRequestWrite("create_pull_request", RestForm(WRITE_METHODS, "pulls")),
    PullRequestWrite(
        "update_pull_request",
        PrCommandForm(
            frozenset({"edit"}),
            any_flag=frozenset({"title", "body", "body-file", "base", "add-reviewer"}),
        ),
    ),
    PullRequestWrite(
        "update_pull_request", PrCommandForm(frozenset({"ready", "close", "reopen"}))
    ),
    PullRequestWrite("update_pull_request", RestForm(WRITE_METHODS, "pulls/*")),
    PullRequestWrite(
        "update_pull_request", RestForm(WRITE_METHODS, "pulls/*/requested_reviewers")
    ),
    PullRequestWrite(
        "update_pull_request", RestForm(WRITE_METHODS, "pulls/*/ccr/ready_for_review")
    ),
    PullRequestWrite(
        "update_pull_request", RestForm(WRITE_METHODS, "pulls/*/ccr/convert_to_draft")
    ),
    PullRequestWrite(
        "enable_pr_auto_merge",
        PrCommandForm(frozenset({"merge"}), any_flag=frozenset({"auto"})),
    ),
    PullRequestWrite(
        "enable_pr_auto_merge", RestForm(WRITE_METHODS, "pulls/*/ccr/auto_merge")
    ),
    PullRequestWrite(
        "disable_pr_auto_merge",
        PrCommandForm(frozenset({"merge"}), any_flag=frozenset({"disable-auto"})),
    ),
    PullRequestWrite(
        "disable_pr_auto_merge", RestForm(DELETE_METHOD, "pulls/*/ccr/auto_merge")
    ),
    PullRequestWrite("merge_pull_request", PrCommandForm(frozenset({"merge"}))),
    PullRequestWrite("merge_pull_request", RestForm(WRITE_METHODS, "pulls/*/merge")),
    PullRequestWrite(
        "update_pull_request_branch",
        PrCommandForm(frozenset({"update-branch"}), absent_flags=frozenset({"rebase"})),
    ),
    PullRequestWrite(
        "update_pull_request_branch", RestForm(WRITE_METHODS, "pulls/*/update-branch")
    ),
    PullRequestWrite("pull_request_review_write", PrCommandForm(frozenset({"review"}))),
    PullRequestWrite(
        "pull_request_review_write", RestForm(WRITE_METHODS, "pulls/*/reviews")
    ),
    PullRequestWrite(
        "pull_request_review_write", RestForm(WRITE_METHODS, "pulls/*/reviews/*/events")
    ),
    PullRequestWrite(
        "pull_request_review_write", RestForm(DELETE_METHOD, "pulls/*/reviews/*")
    ),
    PullRequestWrite(
        "add_reply_to_pull_request_comment",
        RestForm(WRITE_METHODS, "pulls/*/comments", field="in_reply_to"),
    ),
    PullRequestWrite(
        "add_reply_to_pull_request_comment",
        RestForm(WRITE_METHODS, "pulls/*/comments", reads_input=True),
        alternative_tool="add_comment_to_pending_review",
    ),
    PullRequestWrite(
        "add_reply_to_pull_request_comment",
        RestForm(WRITE_METHODS, "pulls/*/comments/*/replies"),
    ),
    PullRequestWrite(
        "add_comment_to_pending_review", RestForm(WRITE_METHODS, "pulls/*/comments")
    ),
    PullRequestWrite(
        "resolve_review_thread",
        RestForm(WRITE_METHODS, "pulls/*/ccr/comments/*/resolve"),
    ),
    PullRequestWrite(
        "unresolve_review_thread",
        RestForm(WRITE_METHODS, "pulls/*/ccr/comments/*/unresolve"),
    ),
    PullRequestWrite(
        "update_issue_comment",
        PrCommandForm(frozenset({"comment"}), any_flag=frozenset({"create-if-none"})),
        alternative_tool="add_issue_comment",
    ),
    PullRequestWrite(
        "update_issue_comment",
        PrCommandForm(frozenset({"comment"}), any_flag=frozenset({"edit-last"})),
    ),
    PullRequestWrite(
        "add_issue_comment",
        PrCommandForm(frozenset({"comment"}), absent_flags=frozenset({"delete-last"})),
    ),
)


def pull_request_write_tools(request: GhRequest) -> list[str]:
    for write in PULL_REQUEST_WRITES:
        if write.form.matches(request):
            return write.tools()
    return []


def mcp_tools_denial(tools: Sequence[str]) -> str:
    named_tools = " or ".join(tools)
    return (
        f"gh: use the GitHub MCP tool {named_tools} for this."
        " The agent that opened a pull request, or its parent, manages it."
        f" If you lack {named_tools}, ask your parent agent to do it."
        " Run gh with ALLOW_GH_PULL_REQUEST_WRITE=1 only when the user asks."
    )


def denial(arguments: Sequence[str]) -> str | None:
    parsed = gh_arguments(arguments)
    if UNCHECKED_FLAGS & parsed.given_flags():
        return None
    request = gh_request(parsed)
    tools = pull_request_write_tools(request) if request else []
    return mcp_tools_denial(tools) if tools else None


def main() -> int:
    message = denial(sys.argv[1:])
    if message is None:
        return 0
    print(message, file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
