import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "mcp"))

from text_positions import to_uri
from workspace_edits import apply_workspace_edit

START = {"line": 0, "character": 0}
INSERT_AT_START = {"range": {"start": START, "end": START}, "newText": "X"}


def test_document_changes_win_over_changes(tmp_path):
    source = tmp_path / "source.py"
    source.write_text("abc")
    uri = to_uri(source)
    apply_workspace_edit(
        {
            "changes": {uri: [INSERT_AT_START]},
            "documentChanges": [
                {"textDocument": {"uri": uri, "version": 1}, "edits": [INSERT_AT_START]}
            ],
        }
    )
    assert source.read_text() == "Xabc"


def test_changes_apply_without_document_changes(tmp_path):
    source = tmp_path / "source.py"
    source.write_text("abc")
    apply_workspace_edit({"changes": {to_uri(source): [INSERT_AT_START]}})
    assert source.read_text() == "Xabc"
