import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "mcp"))

from open_documents import OpenDocuments
from text_positions import to_uri


def notifying_documents():
    notifications = []
    documents = OpenDocuments(
        {".py": "python"}, lambda method, params: notifications.append((method, params))
    )
    return documents, notifications


def sent_versions(notifications):
    return [
        (method, params["textDocument"]["version"]) for method, params in notifications
    ]


def test_edits_after_opening_bump_the_version(tmp_path):
    documents, notifications = notifying_documents()
    source = tmp_path / "main.py"
    source.write_text("a")
    documents.open(source)
    documents.open(source)
    source.write_text("b")
    documents.open(source)
    source.write_text("c")
    documents.open(source)
    assert sent_versions(notifications) == [
        ("textDocument/didOpen", 1),
        ("textDocument/didChange", 2),
        ("textDocument/didChange", 3),
    ]


def test_closed_document_opens_again_at_the_first_version(tmp_path):
    documents, notifications = notifying_documents()
    source = tmp_path / "main.py"
    source.write_text("a")
    documents.open(source)
    documents.close(to_uri(source))
    documents.open(source)
    assert notifications[-1][0] == "textDocument/didOpen"
    assert notifications[-1][1]["textDocument"]["version"] == 1
