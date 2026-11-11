import copy
from collections.abc import Iterable
from typing import NamedTuple

from json_values import JsonObject, JsonValue, dict_or_empty
from transcript import is_conversation_turn, tail_entries


class Prompt(NamedTuple):
    id: str


class Reply(NamedTuple):
    id: str
    is_reply: bool = True


class Window(NamedTuple):
    prompt_id: str
    reply_count: int


class EventLog(NamedTuple):
    next_id: int = 0
    history: tuple[Prompt | Reply, ...] = ()

    def with_reply(self) -> "EventLog":
        reply = Reply(str(self.next_id))
        return EventLog(self.next_id + 1, (*self.history, reply))

    def with_prompt(self) -> "EventLog":
        prompt = Prompt(str(self.next_id))
        return EventLog(self.next_id + 1, (*self.history, prompt))

    def starting_at(self, prompt_id: str) -> "EventLog":
        prompt = Prompt(prompt_id)
        if prompt not in self.history:
            return self
        return copy.replace(self, history=self.history[self.history.index(prompt) :])


def is_wake(message: JsonObject) -> bool:
    kind = dict_or_empty(message.get("origin")).get("kind")
    return isinstance(kind, str) and kind != "human"


def is_queued_human_message(entry: JsonObject) -> bool:
    attachment = dict_or_empty(entry.get("attachment"))
    return attachment.get("type") == "queued_command" and not is_wake(attachment)


def is_human_prompt(entry: JsonObject) -> bool:
    if entry.get("isSidechain") or not isinstance(entry.get("uuid"), str):
        return False
    if entry.get("type") == "user":
        return dict_or_empty(entry.get("origin")).get("kind") == "human"
    return is_queued_human_message(entry)


def reply_text(entry: JsonObject) -> str:
    if entry.get("type") != "assistant" or not is_conversation_turn(entry):
        return ""
    content = dict_or_empty(entry.get("message")).get("content")
    if not isinstance(content, list):
        return ""
    texts = (
        block.get("text")
        for block in content
        if isinstance(block, dict) and block.get("type") == "text"
    )
    return "\n".join(text for text in texts if isinstance(text, str))


def message_id(entry: JsonObject) -> JsonValue:
    return dict_or_empty(entry.get("message")).get("id") or entry.get("uuid")


def transcript_history(transcript_path: str) -> list[Prompt | Reply]:
    history: list[Prompt | Reply] = []
    reply_ids: set[str] = set()
    for entry in tail_entries(transcript_path):
        prompt_id = entry.get("uuid")
        if is_human_prompt(entry) and isinstance(prompt_id, str):
            history.append(Prompt(prompt_id))
            continue
        reply_id = message_id(entry)
        if not (reply_text(entry).strip() and isinstance(reply_id, str)):
            continue
        if reply_id not in reply_ids:
            reply_ids.add(reply_id)
            history.append(Reply(reply_id))
    return history


def windows(history: Iterable[Prompt | Reply]) -> list[Window]:
    found: list[Window] = []
    for item in history:
        if isinstance(item, Prompt):
            found.append(Window(item.id, 0))
        elif found:
            found[-1] = copy.replace(found[-1], reply_count=found[-1].reply_count + 1)
    return found


def window_under_review(
    history: Iterable[Prompt | Reply], remembered: Window, unseen_reply_count: int
) -> Window | None:
    found = windows(history)
    if found:
        return found[-1]
    if not remembered.prompt_id:
        return None
    return copy.replace(
        remembered, reply_count=remembered.reply_count + unseen_reply_count
    )
