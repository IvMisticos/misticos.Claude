import json

type JsonValue = (
    str | int | float | bool | None | list[JsonValue] | dict[str, JsonValue]
)
type JsonObject = dict[str, JsonValue]


def dict_or_empty(value: JsonValue) -> JsonObject:
    return value if isinstance(value, dict) else {}


def json_object(text: str | bytes) -> JsonObject | None:
    try:
        value = json.loads(text)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None
