from collections.abc import Sequence
from pathlib import Path
from typing import NamedTuple

from lsp_types import (
    CallHierarchyItem,
    Diagnostic,
    Hover,
    Location,
    LocationLink,
    MarkedString,
    MarkupContent,
    Position,
    Range,
    Symbol,
)
from text_positions import from_uri, lines_of, position_key, utf16_offset_to_index

type CallSiteKey = tuple[str, int, int]


def location_line(location: Location | LocationLink) -> str:
    uri = location.get("targetUri") or location.get("uri")
    if uri is None:
        return "unknown location"
    range_ = location.get("targetSelectionRange") or location.get("range")
    return range_place(from_uri(uri), range_)


def position_text(path: Path, position: Position) -> str:
    try:
        line_text = lines_of(path)[position["line"]]
    except (OSError, UnicodeDecodeError, IndexError):
        return one_based(position)
    return f"{position['line'] + 1}:{utf16_offset_to_index(line_text, position['character']) + 1}"


def one_based(position: Position) -> str:
    return f"{position['line'] + 1}:{position['character'] + 1}"


def locations_text(
    result: Location | LocationLink | list[Location] | list[LocationLink] | None,
) -> str:
    if not result:
        return "no results"
    items = result if isinstance(result, list) else [result]
    return "\n".join(location_line(item) for item in items)


def hover_text(result: Hover | None) -> str:
    if not result:
        return "no hover information"
    contents = result.get("contents")
    if not contents:
        return "no hover information"
    if isinstance(contents, (str, dict)):
        return hover_part_text(contents)
    return "\n".join(hover_part_text(part) for part in contents)


def hover_part_text(part: MarkedString | MarkupContent) -> str:
    return part if isinstance(part, str) else part.get("value", "")


SHOWN_SEVERITIES: dict[int, str] = {1: "error", 2: "warning", 3: "info"}
DEFAULT_SEVERITY = 1


def severity_of(diagnostic: Diagnostic) -> int:
    return diagnostic.get("severity", DEFAULT_SEVERITY)


def diagnostics_text(path: Path, diagnostics: list[Diagnostic]) -> str:
    shown = sorted(
        (
            diagnostic
            for diagnostic in diagnostics
            if severity_of(diagnostic) in SHOWN_SEVERITIES
        ),
        key=lambda diagnostic: position_key(diagnostic["range"]["start"]),
    )
    lines = [diagnostic_line(path, diagnostic) for diagnostic in shown]
    return "\n".join(lines) or "no errors or warnings"


def diagnostic_line(path: Path, diagnostic: Diagnostic) -> str:
    severity = SHOWN_SEVERITIES[severity_of(diagnostic)]
    code = diagnostic.get("code")
    code_text = f" {code}" if code is not None else ""
    start = place(path, diagnostic["range"]["start"])
    return f"{start} {severity}{code_text}: {diagnostic['message']}"


class Call(NamedTuple):
    function: CallHierarchyItem
    call_site_uri: str
    call_site_ranges: list[Range]


def calls_text(calls: list[Call]) -> str:
    call_sites_by_function: dict[str, dict[CallSiteKey, str]] = {}
    for call in calls:
        call_sites = call_sites_by_function.setdefault(function_line(call.function), {})
        call_sites.update(call_site_places(call))
    blocks = [
        call_block(function, call_sites)
        for function, call_sites in call_sites_by_function.items()
    ]
    return "\n".join(blocks) or "no calls"


def call_site_places(call: Call) -> dict[CallSiteKey, str]:
    path = from_uri(call.call_site_uri)
    return {
        (str(path), *position_key(range_["start"])): place(path, range_["start"])
        for range_ in call.call_site_ranges
    }


def call_block(function: str, call_sites: dict[CallSiteKey, str]) -> str:
    lines = [f"  called at {call_sites[site]}" for site in sorted(call_sites)]
    return "\n".join([function, *lines])


def function_line(function: CallHierarchyItem) -> str:
    definition = place(from_uri(function["uri"]), function["selectionRange"]["start"])
    return f"{function['name']} ({symbol_kind(function['kind'])}) {definition}"


def range_place(path: Path, range_: Range | None) -> str:
    if range_ is None:
        return str(path)
    return place(path, range_["start"])


def place(path: Path, position: Position) -> str:
    return f"{path}:{position_text(path, position)}"


def symbols_text(result: Sequence[Symbol] | None) -> str:
    lines = symbol_lines(result or [], 0)
    return "\n".join(lines) or "no symbols"


def symbol_lines(symbols: Sequence[Symbol], indent: int) -> list[str]:
    lines = []
    for symbol in symbols:
        lines.append(
            f"{'  ' * indent}{symbol['name']} ({symbol_kind(symbol['kind'])}) {symbol_place(symbol)}"
        )
        lines.extend(symbol_lines(symbol.get("children") or [], indent + 1))
    return lines


def symbol_place(symbol: Symbol) -> str:
    location = symbol.get("location") or {}
    path = from_uri(location["uri"]) if "uri" in location else None
    range_ = symbol.get("selectionRange") or location.get("range")
    if path is None:
        return "" if range_ is None else one_based(range_["start"])
    return range_place(path, range_)


SYMBOL_KINDS: dict[int, str] = {
    1: "file",
    2: "module",
    3: "namespace",
    4: "package",
    5: "class",
    6: "method",
    7: "property",
    8: "field",
    9: "constructor",
    10: "enum",
    11: "interface",
    12: "function",
    13: "variable",
    14: "constant",
    15: "string",
    16: "number",
    17: "boolean",
    18: "array",
    19: "object",
    20: "key",
    21: "null",
    22: "enum member",
    23: "struct",
    24: "event",
    25: "operator",
    26: "type parameter",
}


def symbol_kind(kind: int) -> str:
    return SYMBOL_KINDS.get(kind, "symbol")
