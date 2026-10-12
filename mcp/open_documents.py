from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple

from lsp_types import LSPAny
from text_positions import read_text, to_uri

FIRST_VERSION = 1


class OpenedDocument(NamedTuple):
    version: int
    text: str


class OpenDocuments:
    def __init__(
        self, language_ids: dict[str, str], notify: Callable[[str, LSPAny], None]
    ) -> None:
        self.language_ids = language_ids
        self.notify = notify
        self.opened: dict[str, OpenedDocument] = {}

    def open(self, path: Path) -> str:
        text = read_text(path)
        uri = to_uri(path)
        opened = self.opened.get(uri)
        if opened is None:
            self.did_open(uri, self.language_ids[path.suffix], text)
        elif opened.text != text:
            self.did_change(uri, opened.version + 1, text)
        return text

    def did_open(self, uri: str, language_id: str, text: str) -> None:
        self.opened[uri] = OpenedDocument(FIRST_VERSION, text)
        document = {
            "uri": uri,
            "languageId": language_id,
            "version": FIRST_VERSION,
            "text": text,
        }
        self.notify("textDocument/didOpen", {"textDocument": document})

    def did_change(self, uri: str, version: int, text: str) -> None:
        self.opened[uri] = OpenedDocument(version, text)
        self.notify(
            "textDocument/didChange",
            {
                "textDocument": {"uri": uri, "version": version},
                "contentChanges": [{"text": text}],
            },
        )

    def close(self, uri: str) -> None:
        if self.opened.pop(uri, None) is not None:
            self.notify("textDocument/didClose", {"textDocument": {"uri": uri}})
