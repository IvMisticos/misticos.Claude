import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "mcp"))

from lsp_client import LanguageServer
from text_positions import to_uri


def notifying_server(root):
    server = LanguageServer("python", [], {".py": "python"}, root, {})
    notifications = []
    server.notify = lambda method, params: notifications.append((method, params))
    return server, notifications


def sent_versions(notifications):
    return [
        (method, params["textDocument"]["version"]) for method, params in notifications
    ]


def test_edits_after_opening_bump_the_version(tmp_path):
    server, notifications = notifying_server(tmp_path)
    source = tmp_path / "main.py"
    source.write_text("a")
    server.open_document(source)
    server.open_document(source)
    source.write_text("b")
    server.open_document(source)
    source.write_text("c")
    server.open_document(source)
    assert sent_versions(notifications) == [
        ("textDocument/didOpen", 1),
        ("textDocument/didChange", 2),
        ("textDocument/didChange", 3),
    ]


def test_closed_document_opens_again_at_the_first_version(tmp_path):
    server, notifications = notifying_server(tmp_path)
    source = tmp_path / "main.py"
    source.write_text("a")
    server.open_document(source)
    server.close_document(to_uri(source))
    server.open_document(source)
    assert notifications[-1][0] == "textDocument/didOpen"
    assert notifications[-1][1]["textDocument"]["version"] == 1
