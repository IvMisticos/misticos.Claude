import json
import re
from typing import NamedTuple

from transcript import all_entries

NAME = r"[\w.-]+"
PULL_REQUEST_EVENT = re.compile(rf'"pr"\s*:\s*"({NAME})/({NAME})#(\d+)"')
PULL_REQUEST_URL = re.compile(rf"https://github\.com/({NAME})/({NAME})/pull/(\d+)")


class PullRequest(NamedTuple):
    owner: str
    repo: str
    number: int

    def __str__(self):
        return f"{self.owner}/{self.repo}#{self.number}"


def matched_pull_request(match):
    return PullRequest(match[1], match[2], int(match[3]))


def pull_request_in_arguments(arguments):
    owner = arguments.get("owner")
    repo = arguments.get("repo")
    number = arguments.get("pullNumber")
    if isinstance(owner, str) and isinstance(repo, str) and type(number) is int:
        return PullRequest(owner, repo, number)
    return None


def pull_request_in_result(result):
    url = result.get("url")
    match = PULL_REQUEST_URL.fullmatch(url) if isinstance(url, str) else None
    return matched_pull_request(match) if match else None


def embedded_json(text):
    if not text.startswith(("{", "[")):
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def pull_requests_in_object(value):
    named = pull_request_in_arguments(value) or pull_request_in_result(value)
    if named:
        yield named
    for item in value.values():
        yield from pull_requests_in(item)


def pull_requests_in_text(text):
    for match in PULL_REQUEST_EVENT.finditer(text):
        yield matched_pull_request(match)
    yield from pull_requests_in(embedded_json(text))


def pull_requests_in(value):
    if isinstance(value, dict):
        yield from pull_requests_in_object(value)
    elif isinstance(value, list):
        for item in value:
            yield from pull_requests_in(item)
    elif isinstance(value, str):
        yield from pull_requests_in_text(value)


def touched_pull_requests(transcript_path):
    found = (
        pull_request
        for entry in all_entries(transcript_path)
        for pull_request in pull_requests_in(entry)
    )
    return list(dict.fromkeys(found))
