import re

FENCED_CODE = re.compile(
    r"^ {0,3}(([`~])\2{2,})[^\n]*\n.*?(?:^ {0,3}\1\2*[ \t]*$|\Z)",
    re.MULTILINE | re.DOTALL,
)
INLINE_CODE = re.compile(r"(`+)[^\n]+?\1")
LINK = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
AUTOLINK = re.compile(r"<[a-z][a-z0-9+.-]*:[^>\s]*>", re.IGNORECASE)
BARE_URL = re.compile(r"\b[a-z][a-z0-9+.-]*://\S+", re.IGNORECASE)
WHITESPACE = re.compile(r"\s+")


def prose_of(text: str) -> str:
    text = FENCED_CODE.sub(" ", text)
    text = INLINE_CODE.sub(" ", text)
    text = LINK.sub(r"\1", text)
    text = AUTOLINK.sub(" ", text)
    text = BARE_URL.sub(" ", text)
    return WHITESPACE.sub(" ", text).strip()


def prose_length(text: str) -> int:
    return len(prose_of(text))
