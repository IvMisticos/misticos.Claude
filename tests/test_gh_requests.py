import pytest
from gh_requests import path_segments, repository_resource


@pytest.mark.parametrize(
    ("endpoint", "segments"),
    [
        ("repos/o/r//pulls/./1/", ["repos", "o", "r", "pulls", "1"]),
        ("/repos/o/r/pull%73?state=open#top", ["repos", "o", "r", "pulls"]),
        ("repos/o/r/issues/../../x", ["repos", "o", "x"]),
        ("../repos", ["repos"]),
        ("", []),
    ],
)
def test_path_segments_name_the_route_the_server_sees(
    endpoint: str, segments: list[str]
) -> None:
    assert path_segments(endpoint) == segments


@pytest.mark.parametrize(
    ("segments", "resource"),
    [
        (["repos", "o", "r", "pulls", "1"], ("pulls", "1")),
        (["https:", "api.github.com", "repositories", "9", "pulls"], ("pulls",)),
        (["repos", "o", "r"], None),
        (["repositories", "x", "pulls"], None),
        (["user", "repos"], None),
    ],
)
def test_repository_resource_follows_the_repository(
    segments: list[str], resource: tuple[str, ...] | None
) -> None:
    assert repository_resource(segments) == resource
