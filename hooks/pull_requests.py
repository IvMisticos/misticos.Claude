import json
import re
from typing import NamedTuple

from transcript import numbered_entries

NAME = r"[\w.-]+"
PULL_REQUEST_EVENT = re.compile(rf'"pr"\s*:\s*"({NAME})/({NAME})#(\d+)"')
PULL_REQUEST_LINKS = (
    re.compile(rf"github\.com/({NAME})/({NAME})/pull/(\d+)"),
    re.compile(rf"repos/({NAME})/({NAME})/pulls/(\d+)"),
)
CALL_TYPES = frozenset(
    {"tool_use", "function_call", "custom_tool_call", "local_shell_call"}
)
CALL_ID_FIELD_BY_RESULT_TYPE = {
    "tool_result": "tool_use_id",
    "function_call_output": "call_id",
}
CREATE_TOOL_SUFFIX = "create_pull_request"


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


def embedded_json(text):
    if not text.startswith(("{", "[")):
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def nested_values(value):
    yield value
    if isinstance(value, dict):
        value = list(value.values())
    if isinstance(value, list):
        for item in value:
            yield from nested_values(item)


def pull_requests_in_text(text):
    for link in PULL_REQUEST_LINKS:
        yield from map(matched_pull_request, link.finditer(text))
    yield from pull_requests_linked_in(embedded_json(text))


def pull_requests_linked_in(value):
    for item in nested_values(value):
        if isinstance(item, str):
            yield from pull_requests_in_text(item)
        elif isinstance(item, dict) and (named := pull_request_in_arguments(item)):
            yield named


def pull_request_events_in(entry):
    for item in nested_values(entry):
        if isinstance(item, str):
            yield from map(matched_pull_request, PULL_REQUEST_EVENT.finditer(item))


def block_type(block):
    kind = block.get("type")
    return kind if isinstance(kind, str) else ""


def call_id(call):
    found = call.get("call_id") or call.get("id")
    return found if isinstance(found, str) else None


def creates_a_pull_request(call):
    return str(call.get("name") or "").endswith(CREATE_TOOL_SUFFIX)


def answered_call_id(block):
    field = CALL_ID_FIELD_BY_RESULT_TYPE.get(block_type(block))
    answered = block.get(field) if field else None
    return answered if isinstance(answered, str) else None


def pull_requests_in_entry(entry, creating_calls):
    yield from pull_request_events_in(entry)
    blocks = (item for item in nested_values(entry) if isinstance(item, dict))
    for block in blocks:
        if block_type(block) in CALL_TYPES:
            yield from pull_requests_linked_in(block)
            if creates_a_pull_request(block):
                creating_calls.add(call_id(block))
        elif answered_call_id(block) in creating_calls:
            yield from pull_requests_linked_in(block)


def last_activity_by_pull_request(transcript_path):
    last_activity = {}
    creating_calls = set()
    for line_number, entry in numbered_entries(transcript_path):
        for pull_request in pull_requests_in_entry(entry, creating_calls):
            last_activity[pull_request] = line_number
    return last_activity
