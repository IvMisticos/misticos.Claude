from text_positions import LINE_BREAK, from_uri, read_text, utf16_offset_to_index


def apply_workspace_edit(edit):
    document_changes = edit.get("documentChanges") or []
    for change in document_changes:
        if "textDocument" not in change:
            raise ValueError(
                f"the language server wants a file operation ({change.get('kind')}) that this tool does not apply; nothing was written"
            )
    changed = []
    for uri, edits in (edit.get("changes") or {}).items():
        changed.append(apply_text_edits(from_uri(uri), edits))
    for change in document_changes:
        changed.append(
            apply_text_edits(from_uri(change["textDocument"]["uri"]), change["edits"])
        )
    return changed


def apply_text_edits(path, edits):
    text = read_text(path)
    lines = LINE_BREAK.split(text)
    offsets = line_offsets(text)
    for edit in sorted(
        edits,
        key=lambda e: (e["range"]["start"]["line"], e["range"]["start"]["character"]),
        reverse=True,
    ):
        start = text_offset(lines, offsets, edit["range"]["start"])
        end = text_offset(lines, offsets, edit["range"]["end"])
        text = text[:start] + edit["newText"] + text[end:]
    with open(path, "w", encoding="utf-8", newline="") as file:
        file.write(text)
    return str(path)


def text_offset(lines, offsets, position):
    if position["line"] >= len(lines):
        return offsets[-1] + len(lines[-1])
    return offsets[position["line"]] + utf16_offset_to_index(
        lines[position["line"]], position["character"]
    )


def line_offsets(text):
    offsets = [0]
    for match in LINE_BREAK.finditer(text):
        offsets.append(match.end())
    return offsets
