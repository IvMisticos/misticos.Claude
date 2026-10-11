import re

FENCED_CODE = re.compile(
    r"^ {0,3}(`{3,}|~{3,})[^\n]*\n.*?(?:^ {0,3}\1[ \t]*$|\Z)", re.MULTILINE | re.DOTALL
)
INLINE_CODE = re.compile(r"(`+)[^\n]+?\1")
LINK = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
AUTOLINK = re.compile(r"<[a-z][a-z0-9+.-]*:[^>\s]*>", re.IGNORECASE)
BARE_URL = re.compile(r"\b[a-z][a-z0-9+.-]*://\S+", re.IGNORECASE)
WHITESPACE = re.compile(r"\s+")


def prose_of(text):
    text = FENCED_CODE.sub(" ", text)
    text = INLINE_CODE.sub(" ", text)
    text = LINK.sub(r"\1", text)
    text = AUTOLINK.sub(" ", text)
    text = BARE_URL.sub(" ", text)
    return WHITESPACE.sub(" ", text).strip()


def prose_length(text):
    return len(prose_of(text))
