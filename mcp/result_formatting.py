from typing import NamedTuple

from text_positions import from_uri, lines_of, position_key, utf16_offset_to_index


def location_line(location):
    uri = location.get("targetUri") or location.get("uri")
    if uri is None:
        return "unknown location"
    range_ = location.get("targetSelectionRange") or location.get("range")
    path = from_uri(uri)
    if range_ is None:
        return str(path)
    return place(path, range_["start"])


def position_text(path, position):
    try:
        line_text = lines_of(path)[position["line"]]
    except (OSError, UnicodeDecodeError, IndexError):
        return one_based(position)
    return f"{position['line'] + 1}:{utf16_offset_to_index(line_text, position['character']) + 1}"


def one_based(position):
    return f"{position['line'] + 1}:{position['character'] + 1}"


def locations_text(result):
    if not result:
        return "no results"
    items = result if isinstance(result, list) else [result]
    return "\n".join(location_line(item) for item in items)


def hover_text(result):
    if not result:
        return "no hover information"
    contents = result.get("contents")
    if not contents:
        return "no hover information"
    if isinstance(contents, str):
        return contents
    if isinstance(contents, dict):
        return contents.get("value", "")
    return "\n".join(
        part if isinstance(part, str) else part.get("value", "") for part in contents
    )


SHOWN_SEVERITIES = {1: "error", 2: "warning", 3: "info"}


def diagnostics_text(path, diagnostics):
    shown = sorted(
        (
            diagnostic
            for diagnostic in diagnostics
            if diagnostic.get("severity", 1) in SHOWN_SEVERITIES
        ),
        key=lambda diagnostic: position_key(diagnostic["range"]["start"]),
    )
    lines = [diagnostic_line(path, diagnostic) for diagnostic in shown]
    return "\n".join(lines) or "no errors or warnings"


def diagnostic_line(path, diagnostic):
    severity = SHOWN_SEVERITIES[diagnostic.get("severity", 1)]
    code = f" {diagnostic['code']}" if diagnostic.get("code") is not None else ""
    start = place(path, diagnostic["range"]["start"])
    return f"{start} {severity}{code}: {diagnostic['message']}"


class Call(NamedTuple):
    function: dict
    call_site_uri: str
    call_site_ranges: list


def calls_text(calls):
    call_sites_by_function = {}
    for call in calls:
        call_sites = call_sites_by_function.setdefault(function_line(call.function), {})
        call_sites.update(call_site_places(call))
    blocks = [
        call_block(function, call_sites)
        for function, call_sites in call_sites_by_function.items()
    ]
    return "\n".join(blocks) or "no calls"


def call_site_places(call):
    path = from_uri(call.call_site_uri)
    return {
        (str(path), *position_key(range_["start"])): place(path, range_["start"])
        for range_ in call.call_site_ranges
    }


def call_block(function, call_sites):
    lines = [f"  called at {call_sites[site]}" for site in sorted(call_sites)]
    return "\n".join([function, *lines])


def function_line(function):
    definition = place(from_uri(function["uri"]), function["selectionRange"]["start"])
    return f"{function['name']} ({symbol_kind(function.get('kind'))}) {definition}"


def place(path, position):
    return f"{path}:{position_text(path, position)}"


def symbols_text(result):
    lines = symbol_lines(result or [], 0)
    return "\n".join(lines) or "no symbols"


def symbol_lines(symbols, indent):
    lines = []
    for symbol in symbols:
        lines.append(
            f"{'  ' * indent}{symbol['name']} ({symbol_kind(symbol.get('kind'))}) {symbol_place(symbol)}"
        )
        lines.extend(symbol_lines(symbol.get("children") or [], indent + 1))
    return lines


def symbol_place(symbol):
    location = symbol.get("location") or {}
    path = from_uri(location["uri"]) if "uri" in location else None
    range_ = symbol.get("selectionRange") or location.get("range")
    if range_ is None:
        return str(path or "")
    if path is None:
        return one_based(range_["start"])
    return place(path, range_["start"])


SYMBOL_KINDS = {
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


def symbol_kind(kind):
    return SYMBOL_KINDS.get(kind, "symbol")
