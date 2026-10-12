import re
from collections.abc import Callable, Iterator

import tree_sitter_bash
from tree_sitter import Language, Node, Parser

BASH = Parser(Language(tree_sitter_bash.language()))
OPERATOR_IN_DELIMITER = re.compile(rb"[;&|<>()]")
QUOTES = (b"'", b'"')
HEREDOC_END_FOLLOWERS = frozenset({b"", b"\n"})
SUBSTITUTION_CLOSING = b")"
SEPARATORS = frozenset({b";", b"&"})
CHAINING_OPERATOR = b"&&"
LATER_HEREDOC = re.compile(rb"(?<!<)<<(?!<)-?\s*('[^']*'|\"[^\"]*\"|[^\s;&|<>()]+)")
LINE_BREAK = b"\n"
NO_OP_COMMAND = b": "

Correction = Callable[[bytes, Node], bytes | None]


def parsed(source: bytes) -> Node:
    root = BASH.parse(source).root_node
    while (corrected := bash_reading(source, root)) is not None:
        source = corrected
        root = BASH.parse(source).root_node
    return root


def descendants(node: Node) -> Iterator[Node]:
    yield node
    for child in node.children:
        yield from descendants(child)


def bash_reading(source: bytes, root: Node) -> bytes | None:
    for correction in CORRECTIONS:
        for node in descendants(root):
            corrected = correction(source, node)
            if corrected is not None:
                return corrected
    return None


def text_of(source: bytes, node: Node) -> bytes:
    return source[node.start_byte : node.end_byte]


def parent_type(node: Node) -> str | None:
    return node.parent.type if node.parent else None


def inserted(source: bytes, at: int, text: bytes) -> bytes:
    return source[:at] + text + source[at:]


def operator_split_from_delimiter(source: bytes, node: Node) -> bytes | None:
    delimiter = text_of(source, node)
    if node.type != "heredoc_start" or delimiter.startswith(QUOTES):
        return None
    operator = OPERATOR_IN_DELIMITER.search(delimiter)
    if operator is None:
        return None
    return inserted(source, node.start_byte + operator.start(), b" ")


def separator_after_heredoc_read_as_chain(source: bytes, node: Node) -> bytes | None:
    if node.type != "ERROR" or parent_type(node) != "heredoc_redirect":
        return None
    if text_of(source, node) not in SEPARATORS:
        return None
    return source[: node.start_byte] + CHAINING_OPERATOR + source[node.end_byte :]


def body_line_kept_from_ending_heredoc(source: bytes, node: Node) -> bytes | None:
    if node.type != "heredoc_end":
        return None
    follower = source[node.end_byte : node.end_byte + 1]
    if follower in HEREDOC_END_FOLLOWERS:
        return None
    if follower == SUBSTITUTION_CLOSING and is_in_substitution(node):
        return None
    return inserted(source, node.start_byte, b"_")


def is_in_substitution(node: Node) -> bool:
    ancestor = node.parent
    while ancestor is not None:
        if ancestor.type == "command_substitution":
            return True
        ancestor = ancestor.parent
    return False


def failed_arithmetic_split_into_subshells(source: bytes, node: Node) -> bytes | None:
    if node.type != "((" or parent_type(node) != "ERROR":
        return None
    return inserted(source, node.start_byte + 1, b" ")


def later_heredoc_moved_after_first(source: bytes, node: Node) -> bytes | None:
    if node.type != "heredoc_redirect":
        return None
    first_start = first_child_of_type(node, "heredoc_start")
    first_end = first_child_of_type(node, "heredoc_end")
    if first_start is None or first_end is None:
        return None
    line_end = source.find(LINE_BREAK, first_start.end_byte)
    later = LATER_HEREDOC.search(source, first_start.end_byte, line_end)
    if later is None:
        return None
    return (
        source[: later.start()]
        + source[later.end() : first_end.end_byte]
        + LINE_BREAK
        + NO_OP_COMMAND
        + later[0]
        + source[first_end.end_byte :]
    )


def first_child_of_type(node: Node, node_type: str) -> Node | None:
    return next((child for child in node.children if child.type == node_type), None)


CORRECTIONS: list[Correction] = [
    operator_split_from_delimiter,
    separator_after_heredoc_read_as_chain,
    body_line_kept_from_ending_heredoc,
    failed_arithmetic_split_into_subshells,
    later_heredoc_moved_after_first,
]
