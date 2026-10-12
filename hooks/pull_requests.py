import json
import re
from enum import Enum, auto
from typing import NamedTuple

from gh_commands import gh_api_words, gh_argument_lists, gh_pr_call
from transcript import dict_or_empty

NAME = r"[\w.-]+"
LINK_END = r"(?=[/?#]|$)"
PULL_REQUEST_EVENT = re.compile(rf'"pr"\s*:\s*"({NAME})/({NAME})#(\d+)"')
PULL_REQUEST_URL = re.compile(rf"https://github\.com/({NAME})/({NAME})/pull/(\d+)")
PULL_REQUEST_TARGETS = (
    re.compile(rf"https://github\.com/({NAME})/({NAME})/pull/(\d+){LINK_END}"),
    re.compile(
        rf"(?:https://api\.github\.com)?/?repos/({NAME})/({NAME})/pulls/(\d+){LINK_END}"
    ),
)
REPO = re.compile(rf"({NAME})/({NAME})")
CALL_TYPES = frozenset(
    {"tool_use", "function_call", "custom_tool_call", "local_shell_call"}
)
CALL_ID_FIELD_BY_RESULT_TYPE = {
    "tool_result": "tool_use_id",
    "function_call_output": "call_id",
}
ARGUMENT_FIELDS = ("input", "arguments", "action")
TARGET_FIELDS = ("url", "path")
GITHUB_TOOL_MARKER = "github"
CREATE_TOOL_SUFFIX = "create_pull_request"
NOTIFICATIONS_TOOL_SUFFIX = "readnotifications"
USER = "user"
TEXT = "text"


class ResultUse(Enum):
    CREATED_PULL_REQUEST = auto()
    NOTIFICATIONS = auto()


class PullRequest(NamedTuple):
    owner: str
    repo: str
    number: int

    def __str__(self):
        return f"{self.owner}/{self.repo}#{self.number}"


def matched_pull_request(match):
    return PullRequest(match[1], match[2], int(match[3]))


def targeted_pull_request(word):
    for target in PULL_REQUEST_TARGETS:
        if match := target.match(word):
            return matched_pull_request(match)
    return None


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


def nested_texts(value):
    return (item for item in nested_values(value) if isinstance(item, str))


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


def gh_calls(call):
    arguments = call_arguments(call)
    return gh_argument_lists(arguments.get("command") or arguments.get("cmd"))


def pull_request_of_gh_pr_call(pr_call):
    if not pr_call or pr_call.target is None:
        return None
    if targeted := targeted_pull_request(pr_call.target):
        return targeted
    repo = pr_call.repo and REPO.fullmatch(pr_call.repo)
    if repo and pr_call.target.isdigit():
        return PullRequest(repo[1], repo[2], int(pr_call.target))
    return None


def pull_requests_in_gh_call(arguments):
    targets = [pull_request_of_gh_pr_call(gh_pr_call(arguments))]
    targets += map(targeted_pull_request, gh_api_words(arguments))
    return [target for target in targets if target]


def pull_requests_in_github_tool(arguments):
    targets = (arguments.get(field) for field in TARGET_FIELDS)
    found = (targeted_pull_request(t) for t in targets if isinstance(t, str))
    return [target for target in found if target]


def pull_requests_in_call(call):
    arguments = call_arguments(call)
    if named := pull_request_in_arguments(arguments):
        yield named
    if GITHUB_TOOL_MARKER in call_name(call):
        yield from pull_requests_in_github_tool(arguments)
    for gh_arguments in gh_calls(call):
        yield from pull_requests_in_gh_call(gh_arguments)


def creates_by_gh(call):
    pr_calls = (gh_pr_call(arguments) for arguments in gh_calls(call))
    return any(pr_call and pr_call.creates_a_pull_request() for pr_call in pr_calls)


def result_use(call):
    name = call_name(call)
    if name.endswith(CREATE_TOOL_SUFFIX) or creates_by_gh(call):
        return ResultUse.CREATED_PULL_REQUEST
    if name.endswith(NOTIFICATIONS_TOOL_SUFFIX):
        return ResultUse.NOTIFICATIONS
    return None


def answered_call_id(block):
    field = CALL_ID_FIELD_BY_RESULT_TYPE.get(block_type(block))
    answered = block.get(field) if field else None
    return answered if isinstance(answered, str) else None


def pull_request_events_in(texts):
    for text in texts:
        yield from map(matched_pull_request, PULL_REQUEST_EVENT.finditer(text))


def pull_requests_linked_in(texts):
    for text in texts:
        yield from map(matched_pull_request, PULL_REQUEST_URL.finditer(text))


def pull_requests_in_result(result, use):
    match use:
        case ResultUse.CREATED_PULL_REQUEST:
            return pull_requests_linked_in(nested_texts(result))
        case ResultUse.NOTIFICATIONS:
            return pull_request_events_in(nested_texts(result))
        case _:
            return []


def user_texts(entry):
    if block_type(entry) != USER:
        return
    content = dict_or_empty(entry.get("message")).get("content")
    blocks = content if isinstance(content, list) else [content]
    for block in blocks:
        if isinstance(block, str):
            yield block
        elif isinstance(block, dict) and block_type(block) == TEXT:
            yield from nested_texts(block.get("text"))


def pull_requests_in_entry(entry, result_uses):
    yield from pull_request_events_in(user_texts(entry))
    blocks = (item for item in nested_values(entry) if isinstance(item, dict))
    for block in blocks:
        if block_type(block) not in CALL_TYPES:
            use = result_uses.get(answered_call_id(block))
            yield from pull_requests_in_result(block, use)
            continue
        yield from pull_requests_in_call(block)
        use = result_use(block)
        if use and call_id(block):
            result_uses[call_id(block)] = use


def last_activity_by_pull_request(entries_with_positions):
    last_activity = {}
    result_uses = {}
    for position, entry in entries_with_positions:
        for pull_request in pull_requests_in_entry(entry, result_uses):
            last_activity[pull_request] = position
    return last_activity
