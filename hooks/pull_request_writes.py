import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from typing import NamedTuple

from gh_commands import has_flag
from gh_requests import (
    GhRequest,
    GraphqlQueryFromFile,
    GraphqlRequest,
    PrCommand,
    RestRequest,
    gh_request,
)

ANY_SEGMENT = "*"
NAME_CHARACTER = "[_A-Za-z0-9]"
UNCHECKED_FLAGS = ("--help", "-h", "--attach")
ALLOW_HINT = "Run gh with ALLOW_GH_PULL_REQUEST_WRITE=1 only when the user asks."
UNCHECKED_QUERY_DENIAL = (
    "gh: pass the GraphQL query inline with -f query=..., not from a file"
    " or standard input, so gh can check it for pull request writes."
    f" {ALLOW_HINT}"
)


def mentions(text: str, word: str) -> bool:
    alone = rf"(?<!{NAME_CHARACTER}){re.escape(word)}(?!{NAME_CHARACTER})"
    return re.search(alone, text) is not None


def resource_matches(pattern: str, resource: str) -> bool:
    pattern_segments = pattern.split("/")
    segments = resource.split("/")
    if len(segments) != len(pattern_segments):
        return False
    return all(
        expected == segment or (expected == ANY_SEGMENT and segment != "")
        for expected, segment in zip(pattern_segments, segments, strict=True)
    )


@dataclass(frozen=True)
class PrCommandForm:
    subcommand: str
    flag: str | None = None
    absent_flags: tuple[str, ...] = ()

    def matches(self, request: GhRequest) -> bool:
        if not isinstance(request, PrCommand) or request.subcommand != self.subcommand:
            return False
        if self.flag is not None and not has_flag(request.arguments, self.flag):
            return False
        return not any(has_flag(request.arguments, flag) for flag in self.absent_flags)


@dataclass(frozen=True)
class RestForm:
    method: str
    resource: str
    field: str | None = None
    reads_input: bool = False

    def matches(self, request: GhRequest) -> bool:
        if not isinstance(request, RestRequest) or request.method != self.method:
            return False
        if not resource_matches(self.resource, request.resource):
            return False
        if self.field is not None and self.field not in request.field_names:
            return False
        return request.reads_input or not self.reads_input


@dataclass(frozen=True)
class GraphqlForm:
    mutation: str
    in_fields: str | None = None
    not_in_fields: str | None = None

    def matches(self, request: GhRequest) -> bool:
        if not isinstance(request, GraphqlRequest):
            return False
        if self.in_fields and not fields_mention(request, self.in_fields):
            return False
        if self.not_in_fields and fields_mention(request, self.not_in_fields):
            return False
        return mentions(request.query, self.mutation)


def fields_mention(request: GraphqlRequest, word: str) -> bool:
    return any(mentions(field, word) for field in request.fields)


class PullRequestWrite(NamedTuple):
    tool: str
    form: PrCommandForm | RestForm | GraphqlForm


PULL_REQUEST_WRITES = (
    PullRequestWrite("create_pull_request", PrCommandForm("create")),
    PullRequestWrite("create_pull_request", PrCommandForm("new")),
    PullRequestWrite("create_pull_request", RestForm("POST", "pulls")),
    PullRequestWrite("create_pull_request", GraphqlForm("createPullRequest")),
    PullRequestWrite("update_pull_request", PrCommandForm("edit", "--title")),
    PullRequestWrite("update_pull_request", PrCommandForm("edit", "-t")),
    PullRequestWrite("update_pull_request", PrCommandForm("edit", "--body")),
    PullRequestWrite("update_pull_request", PrCommandForm("edit", "-b")),
    PullRequestWrite("update_pull_request", PrCommandForm("edit", "--body-file")),
    PullRequestWrite("update_pull_request", PrCommandForm("edit", "-F")),
    PullRequestWrite("update_pull_request", PrCommandForm("edit", "--base")),
    PullRequestWrite("update_pull_request", PrCommandForm("edit", "-B")),
    PullRequestWrite("update_pull_request", PrCommandForm("edit", "--add-reviewer")),
    PullRequestWrite("update_pull_request", PrCommandForm("ready")),
    PullRequestWrite("update_pull_request", PrCommandForm("close")),
    PullRequestWrite("update_pull_request", PrCommandForm("reopen")),
    PullRequestWrite("update_pull_request", RestForm("PATCH", "pulls/*")),
    PullRequestWrite(
        "update_pull_request", RestForm("POST", "pulls/*/requested_reviewers")
    ),
    PullRequestWrite(
        "update_pull_request", RestForm("POST", "pulls/*/ccr/ready_for_review")
    ),
    PullRequestWrite(
        "update_pull_request", RestForm("POST", "pulls/*/ccr/convert_to_draft")
    ),
    PullRequestWrite("update_pull_request", GraphqlForm("updatePullRequest")),
    PullRequestWrite("update_pull_request", GraphqlForm("closePullRequest")),
    PullRequestWrite("update_pull_request", GraphqlForm("reopenPullRequest")),
    PullRequestWrite(
        "update_pull_request", GraphqlForm("markPullRequestReadyForReview")
    ),
    PullRequestWrite("update_pull_request", GraphqlForm("convertPullRequestToDraft")),
    PullRequestWrite("update_pull_request", GraphqlForm("requestReviews")),
    PullRequestWrite("update_pull_request", GraphqlForm("requestReviewsByLogin")),
    PullRequestWrite("enable_pr_auto_merge", PrCommandForm("merge", "--auto")),
    PullRequestWrite("enable_pr_auto_merge", RestForm("PUT", "pulls/*/ccr/auto_merge")),
    PullRequestWrite("enable_pr_auto_merge", GraphqlForm("enablePullRequestAutoMerge")),
    PullRequestWrite("disable_pr_auto_merge", PrCommandForm("merge", "--disable-auto")),
    PullRequestWrite(
        "disable_pr_auto_merge", RestForm("DELETE", "pulls/*/ccr/auto_merge")
    ),
    PullRequestWrite(
        "disable_pr_auto_merge", GraphqlForm("disablePullRequestAutoMerge")
    ),
    PullRequestWrite("merge_pull_request", PrCommandForm("merge")),
    PullRequestWrite("merge_pull_request", RestForm("PUT", "pulls/*/merge")),
    PullRequestWrite("merge_pull_request", GraphqlForm("mergePullRequest")),
    PullRequestWrite(
        "update_pull_request_branch",
        PrCommandForm("update-branch", absent_flags=("--rebase",)),
    ),
    PullRequestWrite(
        "update_pull_request_branch", RestForm("PUT", "pulls/*/update-branch")
    ),
    PullRequestWrite(
        "update_pull_request_branch",
        GraphqlForm("updatePullRequestBranch", not_in_fields="REBASE"),
    ),
    PullRequestWrite("pull_request_review_write", PrCommandForm("review")),
    PullRequestWrite("pull_request_review_write", RestForm("POST", "pulls/*/reviews")),
    PullRequestWrite(
        "pull_request_review_write", RestForm("POST", "pulls/*/reviews/*/events")
    ),
    PullRequestWrite(
        "pull_request_review_write", RestForm("DELETE", "pulls/*/reviews/*")
    ),
    PullRequestWrite("pull_request_review_write", GraphqlForm("addPullRequestReview")),
    PullRequestWrite(
        "pull_request_review_write", GraphqlForm("submitPullRequestReview")
    ),
    PullRequestWrite(
        "pull_request_review_write", GraphqlForm("deletePullRequestReview")
    ),
    PullRequestWrite(
        "add_reply_to_pull_request_comment",
        RestForm("POST", "pulls/*/comments", field="in_reply_to"),
    ),
    PullRequestWrite(
        "add_reply_to_pull_request_comment",
        RestForm("POST", "pulls/*/comments", reads_input=True),
    ),
    PullRequestWrite(
        "add_reply_to_pull_request_comment",
        RestForm("POST", "pulls/*/comments/*/replies"),
    ),
    PullRequestWrite(
        "add_reply_to_pull_request_comment",
        RestForm("POST", "pulls/comments/*/reactions"),
    ),
    PullRequestWrite(
        "add_reply_to_pull_request_comment",
        GraphqlForm("addPullRequestReviewComment", in_fields="inReplyTo"),
    ),
    PullRequestWrite(
        "add_reply_to_pull_request_comment",
        GraphqlForm("addPullRequestReviewThreadReply"),
    ),
    PullRequestWrite(
        "add_comment_to_pending_review",
        RestForm("POST", "pulls/*/comments", reads_input=True),
    ),
    PullRequestWrite(
        "add_comment_to_pending_review", RestForm("POST", "pulls/*/comments")
    ),
    PullRequestWrite(
        "add_comment_to_pending_review", GraphqlForm("addPullRequestReviewComment")
    ),
    PullRequestWrite(
        "add_comment_to_pending_review", GraphqlForm("addPullRequestReviewThread")
    ),
    PullRequestWrite(
        "resolve_review_thread", RestForm("POST", "pulls/*/ccr/comments/*/resolve")
    ),
    PullRequestWrite("resolve_review_thread", GraphqlForm("resolveReviewThread")),
    PullRequestWrite(
        "unresolve_review_thread", RestForm("POST", "pulls/*/ccr/comments/*/unresolve")
    ),
    PullRequestWrite("unresolve_review_thread", GraphqlForm("unresolveReviewThread")),
    PullRequestWrite("add_issue_comment", PrCommandForm("comment", "--create-if-none")),
    PullRequestWrite(
        "add_issue_comment",
        PrCommandForm("comment", absent_flags=("--edit-last", "--delete-last")),
    ),
)


def pull_request_write_tools(request: GhRequest) -> list[str]:
    first_match = next(
        (write.form for write in PULL_REQUEST_WRITES if write.form.matches(request)),
        None,
    )
    return [write.tool for write in PULL_REQUEST_WRITES if write.form == first_match]


def mcp_tools_denial(tools: Sequence[str]) -> str:
    named_tools = " or ".join(tools)
    return (
        f"gh: use the GitHub MCP tool {named_tools} for this."
        " The agent that opened a pull request, or its parent, manages it."
        f" If you lack {named_tools}, ask your parent agent to do it."
        f" {ALLOW_HINT}"
    )


def skips_the_check(arguments: Sequence[str]) -> bool:
    return any(has_flag(arguments, flag) for flag in UNCHECKED_FLAGS)


def denial(arguments: Sequence[str]) -> str | None:
    if skips_the_check(arguments):
        return None
    request = gh_request(arguments)
    if request is None:
        return None
    if isinstance(request, GraphqlQueryFromFile):
        return UNCHECKED_QUERY_DENIAL
    tools = pull_request_write_tools(request)
    return mcp_tools_denial(tools) if tools else None


def main() -> int:
    message = denial(sys.argv[1:])
    if message is None:
        return 0
    print(message, file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
