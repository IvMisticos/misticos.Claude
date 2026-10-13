from typing import NamedTuple

from json_values import dict_or_empty
from prose import prose_length
from transcript import is_conversation_turn, tail_entries


class Prompt(NamedTuple):
    id: str


class Reply(NamedTuple):
    id: str
    prose_length: int


class Window(NamedTuple):
    prompt_id: str
    reply_count: int


class EventLog(NamedTuple):
    next_id: int = 0
    history: tuple = ()

    def with_reply(self, text):
        reply = Reply(str(self.next_id), prose_length(text))
        return EventLog(self.next_id + 1, (*self.history, reply))

    def with_prompt(self):
        prompt = Prompt(str(self.next_id))
        return EventLog(self.next_id + 1, (*self.history, prompt))

    def starting_at(self, prompt_id):
        prompt = Prompt(prompt_id)
        if prompt not in self.history:
            return self
        return self._replace(history=self.history[self.history.index(prompt) :])

    def to_json(self):
        return {
            "next_id": self.next_id,
            "history": [
                {"reply": item.id, "length": item.prose_length}
                if isinstance(item, Reply)
                else {"prompt": item.id}
                for item in self.history
            ],
        }


def parsed_history_item(stored):
    stored = dict_or_empty(stored)
    if isinstance(stored.get("prompt"), str):
        return Prompt(stored["prompt"])
    if isinstance(stored.get("reply"), str) and isinstance(stored.get("length"), int):
        return Reply(stored["reply"], stored["length"])
    return None


def parsed_event_log(stored):
    stored = dict_or_empty(stored)
    next_id = stored.get("next_id")
    history = stored.get("history")
    if not (isinstance(next_id, int) and isinstance(history, list)):
        return EventLog()
    items = (parsed_history_item(item) for item in history)
    return EventLog(next_id, tuple(item for item in items if item))


def is_wake(message):
    kind = dict_or_empty(message.get("origin")).get("kind")
    return isinstance(kind, str) and kind != "human"


def is_queued_human_message(entry):
    attachment = dict_or_empty(entry.get("attachment"))
    return attachment.get("type") == "queued_command" and not is_wake(attachment)


def is_human_prompt(entry):
    if entry.get("isSidechain") or not isinstance(entry.get("uuid"), str):
        return False
    if entry.get("type") == "user":
        return dict_or_empty(entry.get("origin")).get("kind") == "human"
    return is_queued_human_message(entry)


def reply_text(entry):
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


def message_id(entry):
    return dict_or_empty(entry.get("message")).get("id") or entry.get("uuid")


def transcript_history(transcript_path):
    if not transcript_path:
        return []
    history = []
    reply_texts = {}
    for entry in tail_entries(transcript_path):
        if is_human_prompt(entry):
            history.append(Prompt(entry["uuid"]))
            continue
        text = reply_text(entry)
        reply_id = message_id(entry)
        if not (text.strip() and isinstance(reply_id, str)):
            continue
        if reply_id not in reply_texts:
            history.append(reply_id)
        reply_texts[reply_id] = "\n".join(
            filter(None, [reply_texts.get(reply_id), text])
        )
    return [
        Reply(item, prose_length(reply_texts[item])) if isinstance(item, str) else item
        for item in history
    ]


def without_trailing_prompts(history):
    end = len(history)
    while end and isinstance(history[end - 1], Prompt):
        end -= 1
    return history[:end]


def windows(history):
    found = []
    for item in history:
        if isinstance(item, Prompt):
            found.append(Window(item.id, 0))
        elif found:
            found[-1] = found[-1]._replace(reply_count=found[-1].reply_count + 1)
    return found


def window_under_review(history, remembered, unseen_reply_count):
    found = windows(history)
    if found:
        return found[-1]
    if not remembered.prompt_id:
        return None
    return remembered._replace(reply_count=remembered.reply_count + unseen_reply_count)
