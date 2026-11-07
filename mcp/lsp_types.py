from typing import Any, NotRequired, TypedDict

type LSPAny = Any


class Position(TypedDict):
    line: int
    character: int


class Range(TypedDict):
    start: Position
    end: Position


class Location(TypedDict):
    uri: str
    range: Range


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
type HoverContents = MarkedString | MarkupContent | list[MarkedString]


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


class SymbolLocation(TypedDict):
    uri: str
    range: NotRequired[Range]


class WorkspaceSymbol(TypedDict):
    name: str
    kind: int
    location: SymbolLocation


type Symbol = DocumentSymbol | WorkspaceSymbol


class CallHierarchyItem(TypedDict):
    name: str
    kind: int
    tags: NotRequired[list[int]]
    detail: NotRequired[str]
    uri: str
    range: Range
    selectionRange: Range
    data: NotRequired[LSPAny]


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


class InitializeResult(TypedDict):
    capabilities: dict[str, LSPAny]


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
