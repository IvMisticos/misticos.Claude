from typing import Any, NotRequired, TypedDict

from pydantic import with_config

type LSPAny = Any


class Position(TypedDict):
    line: int
    character: int


class Range(TypedDict):
    start: Position
    end: Position


class Location(TypedDict):
    uri: str
    range: NotRequired[Range]


class LocationLink(TypedDict):
    targetUri: str
    targetRange: Range
    targetSelectionRange: Range


class MarkupContent(TypedDict):
    kind: str
    value: str


class LanguageString(TypedDict):
    language: str
    value: str


type MarkedString = str | LanguageString
type HoverContents = MarkedString | MarkupContent | list[MarkedString | MarkupContent]


class Hover(TypedDict):
    contents: HoverContents


class Diagnostic(TypedDict):
    range: Range
    message: str
    severity: NotRequired[int]
    code: NotRequired[int | str]


class FullDocumentDiagnosticReport(TypedDict):
    items: list[Diagnostic]


class DocumentSymbol(TypedDict):
    name: str
    kind: int
    range: Range
    selectionRange: Range
    children: NotRequired[list["DocumentSymbol"]]


class WorkspaceSymbol(TypedDict):
    name: str
    kind: int
    location: Location


type Symbol = DocumentSymbol | WorkspaceSymbol


@with_config(extra="allow")
class CallHierarchyItem(TypedDict):
    name: str
    kind: int
    uri: str
    range: Range
    selectionRange: Range


CallHierarchyIncomingCall = TypedDict(
    "CallHierarchyIncomingCall", {"from": CallHierarchyItem, "fromRanges": list[Range]}
)


class CallHierarchyOutgoingCall(TypedDict):
    to: CallHierarchyItem
    fromRanges: list[Range]


class TextEdit(TypedDict):
    range: Range
    newText: str


class VersionedTextDocumentIdentifier(TypedDict):
    uri: str
    version: int | None


class TextDocumentEdit(TypedDict):
    textDocument: VersionedTextDocumentIdentifier
    edits: list[TextEdit]


class ResourceOperation(TypedDict):
    kind: str


class WorkspaceEdit(TypedDict, total=False):
    changes: dict[str, list[TextEdit]]
    documentChanges: list[TextDocumentEdit | ResourceOperation]


class FileEvent(TypedDict):
    uri: str
    type: int


class ResponseError(TypedDict):
    code: int
    message: str


type RequestId = int | str


class Request(TypedDict):
    jsonrpc: str
    id: RequestId
    method: str
    params: NotRequired[LSPAny]


class Notification(TypedDict):
    jsonrpc: str
    method: str
    params: NotRequired[LSPAny]


class Response(TypedDict):
    jsonrpc: str
    id: RequestId
    result: NotRequired[object]
    error: NotRequired[ResponseError]


type Message = Request | Notification | Response
