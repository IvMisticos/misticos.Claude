from collections.abc import Iterable, Sequence
from pathlib import Path

from lsp_types import (
    Position,
    ResourceOperation,
    TextDocumentEdit,
    TextEdit,
    WorkspaceEdit,
)
from text_positions import (
    LINE_BREAK,
    from_uri,
    position_key,
    read_text,
    utf16_offset_to_index,
)


def apply_workspace_edit(edit: WorkspaceEdit) -> list[str]:
    document_changes = edit.get("documentChanges")
    if document_changes is None:
        edits_by_uri = (edit.get("changes") or {}).items()
    else:
        edits_by_uri = text_edits_by_uri(document_changes)
    return [apply_text_edits(from_uri(uri), edits) for uri, edits in edits_by_uri]


def text_edits_by_uri(
    document_changes: Iterable[TextDocumentEdit | ResourceOperation],
) -> list[tuple[str, list[TextEdit]]]:
    edits_by_uri: list[tuple[str, list[TextEdit]]] = []
    for change in document_changes:
        if "kind" in change:
            raise ValueError(
                f"the language server wants a file operation ({change.get('kind')}) that this tool does not apply; nothing was written"
            )
        edits_by_uri.append((change["textDocument"]["uri"], change["edits"]))
    return edits_by_uri


def apply_text_edits(path: Path, edits: Iterable[TextEdit]) -> str:
    text = read_text(path)
    lines = LINE_BREAK.split(text)
    offsets = line_offsets(text)
    for edit in sorted(
        edits,
        key=lambda e: position_key(e["range"]["start"]),
        reverse=True,
    ):
        start = text_offset(lines, offsets, edit["range"]["start"])
        end = text_offset(lines, offsets, edit["range"]["end"])
        text = text[:start] + edit["newText"] + text[end:]
    with open(path, "w", encoding="utf-8", newline="") as file:
        file.write(text)
    return str(path)


def text_offset(
    lines: Sequence[str], offsets: Sequence[int], position: Position
) -> int:
    if position["line"] >= len(lines):
        return offsets[-1] + len(lines[-1])
    return offsets[position["line"]] + utf16_offset_to_index(
        lines[position["line"]], position["character"]
    )


def line_offsets(text: str) -> list[int]:
    return [0, *(match.end() for match in LINE_BREAK.finditer(text))]
