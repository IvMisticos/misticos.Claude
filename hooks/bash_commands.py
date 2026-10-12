import re
from itertools import pairwise
from pathlib import PurePosixPath

from bash_parsing import descendants, parsed
from tree_sitter import Node

SHELLS = frozenset({"bash", "dash", "sh", "zsh"})
ESCAPED_CHARACTER = re.compile(r"\\(.)", re.DOTALL)
DOUBLE_QUOTE_ESCAPES = frozenset('$`"\\\n')
ANSI_C_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "\\": "\\", "'": "'", '"': '"'}
LINE_CONTINUATION = "\n"


def command_words(text: str) -> list[list[str]]:
    root = parsed(text.encode())
    commands = (words_of(node) for node in descendants(root) if node.type == "command")
    return [run for words in commands if words for run in run_by(words)]


def words_of(command: Node) -> list[str]:
    name = command.child_by_field_name("name")
    if name is None:
        return []
    arguments = command.children_by_field_name("argument")
    return [unquoted(word) for word in [name, *arguments]]


def run_by(words: list[str]) -> list[list[str]]:
    script = shell_script(words)
    return [words] if script is None else [words, *command_words(script)]


def shell_script(words: list[str]) -> str | None:
    if PurePosixPath(words[0]).name not in SHELLS:
        return None
    for flag, script in pairwise(words[1:]):
        if is_command_string_flag(flag):
            return script
    return None


def is_command_string_flag(word: str) -> bool:
    return word.startswith("-") and not word.startswith("--") and "c" in word


def unquoted(node: Node) -> str:
    text = (node.text or b"").decode()
    match node.type:
        case "command_name" | "concatenation":
            return "".join(unquoted(child) for child in node.children)
        case "word":
            return ESCAPED_CHARACTER.sub(unescaped, text)
        case "raw_string":
            return text[1:-1]
        case "string":
            return ESCAPED_CHARACTER.sub(double_quote_unescaped, text[1:-1])
        case "ansi_c_string":
            return ESCAPED_CHARACTER.sub(ansi_c_unescaped, text[2:-1])
    return text


def unescaped(escape: re.Match[str]) -> str:
    character = escape[1]
    return "" if character == LINE_CONTINUATION else character


def double_quote_unescaped(escape: re.Match[str]) -> str:
    if escape[1] not in DOUBLE_QUOTE_ESCAPES:
        return escape[0]
    return unescaped(escape)


def ansi_c_unescaped(escape: re.Match[str]) -> str:
    return ANSI_C_ESCAPES.get(escape[1], escape[0])
