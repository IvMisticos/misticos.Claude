import pytest
from gh_requests import (
    GhRequest,
    GraphqlQueryFromFile,
    GraphqlRequest,
    PrCommand,
    RestRequest,
    gh_request,
)


@pytest.mark.parametrize(
    ("arguments", "request_record"),
    [
        (
            ["-R", "o/r", "pr", "merge", "1"],
            PrCommand("merge", ("-R", "o/r", "pr", "merge", "1")),
        ),
        (
            ["api", "-iXpatch", "repos/o/r/pulls/1"],
            RestRequest("PATCH", "pulls/1", frozenset(), reads_input=False),
        ),
        (
            ["api", "repos/o/r/issues/1/labels?x=1", "-f", "labels[]=x"],
            RestRequest("POST", "issues/1/labels", frozenset({"labels"}), False),
        ),
        (
            ["api", "https://api.github.com/repositories/9/pulls/", "--input", "-"],
            RestRequest("POST", "pulls", frozenset(), reads_input=True),
        ),
        (
            ["api", "graphql", "-f", "query=q", "-F", "n=1"],
            GraphqlRequest("q", ("query=q", "n=1")),
        ),
        (["api", "graphql", "-F", "query=@q.graphql"], GraphqlQueryFromFile()),
    ],
)
def test_parses_the_request_gh_sends(
    arguments: list[str], request_record: GhRequest
) -> None:
    assert gh_request(arguments) == request_record


@pytest.mark.parametrize(
    "arguments",
    [["pr"], ["issue", "create"], ["api", "user"], ["api"], ["--", "pr", "merge"]],
)
def test_finds_no_request_it_checks(arguments: list[str]) -> None:
    assert gh_request(arguments) is None
