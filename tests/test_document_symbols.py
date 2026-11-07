import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "mcp"))

from lsp_types import DocumentSymbol, Position, Range
from result_formatting import document_symbols_text

CLASS, METHOD = 5, 6


def starting_at(line: int, character: int) -> Range:
    position: Position = {"line": line, "character": character}
    return {"start": position, "end": position}


def test_children_nest_under_their_parent_at_character_columns(
    tmp_path: Path,
) -> None:
    source = tmp_path / "greeter.ts"
    source.write_text("/* 😀 */ class Greeter {\n  greet() {}\n}\n", encoding="utf-8")
    greet: DocumentSymbol = {
        "name": "greet",
        "kind": METHOD,
        "range": starting_at(1, 2),
        "selectionRange": starting_at(1, 2),
    }
    greeter: DocumentSymbol = {
        "name": "Greeter",
        "kind": CLASS,
        "range": starting_at(0, 9),
        "selectionRange": starting_at(0, 15),
        "children": [greet],
    }
    assert document_symbols_text(source, [greeter]).splitlines() == [
        f"Greeter (class) {source}:1:15",
        f"  greet (method) {source}:2:3",
    ]
