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
GITHUB_TOOL_MARKER = "github"
ASSISTANT = "assistant"
ARGUMENT_FIELDS = ("input", "arguments", "action")
GH_COMMAND = re.compile(r"(?:^|[\s;&|(`])gh\s")
GH_PR_CREATE = re.compile(r"\bgh\s+pr\s+create\b")


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


def texts_outside_calls(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from texts_outside_calls(item)
    elif isinstance(value, dict) and block_type(value) not in CALL_TYPES:
        for item in value.values():
            yield from texts_outside_calls(item)


def pull_request_events_in(entry):
    if block_type(entry) == ASSISTANT:
        return
    for text in texts_outside_calls(entry):
        yield from map(matched_pull_request, PULL_REQUEST_EVENT.finditer(text))


def block_type(block):
    kind = block.get("type")
    return kind if isinstance(kind, str) else ""


def call_id(call):
    found = call.get("call_id") or call.get("id")
    return found if isinstance(found, str) else None


def call_name(call):
    name = call.get("name")
    return name.lower() if isinstance(name, str) else ""


def call_arguments(call):
    for field in ARGUMENT_FIELDS:
        value = call.get(field)
        arguments = embedded_json(value) if isinstance(value, str) else value
        if isinstance(arguments, dict):
            return arguments
    return {}


def shell_command(arguments):
    command = arguments.get("command") or arguments.get("cmd")
    if isinstance(command, list):
        command = " ".join(part for part in command if isinstance(part, str))
    return command if isinstance(command, str) else ""


def gh_command(call):
    command = shell_command(call_arguments(call))
    return command if GH_COMMAND.search(command) else ""


def creates_a_pull_request(call):
    return call_name(call).endswith(CREATE_TOOL_SUFFIX) or bool(
        GH_PR_CREATE.search(gh_command(call))
    )


def pull_requests_in_call(call):
    arguments = call_arguments(call)
    if named := pull_request_in_arguments(arguments):
        yield named
    if GITHUB_TOOL_MARKER in call_name(call):
        yield from pull_requests_linked_in(arguments)
    yield from pull_requests_in_text(gh_command(call))


def answered_call_id(block):
    field = CALL_ID_FIELD_BY_RESULT_TYPE.get(block_type(block))
    answered = block.get(field) if field else None
    return answered if isinstance(answered, str) else None


def pull_requests_in_entry(entry, creating_calls):
    yield from pull_request_events_in(entry)
    blocks = (item for item in nested_values(entry) if isinstance(item, dict))
    for block in blocks:
        if block_type(block) in CALL_TYPES:
            yield from pull_requests_in_call(block)
            if creates_a_pull_request(block) and call_id(block):
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
