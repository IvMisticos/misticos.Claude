import json


def dict_or_empty(value):
    return value if isinstance(value, dict) else {}


def json_object(text):
    try:
        value = json.loads(text)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def read_json_file(path):
    try:
        text = path.read_text()
    except FileNotFoundError:
        return {}
    return json.loads(text) if text.strip() else {}
