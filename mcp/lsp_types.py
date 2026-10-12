from typing import Any, NotRequired, TypeAlias, TypedDict

LSPAny: TypeAlias = Any


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
    originSelectionRange: NotRequired[Range]


class MarkupContent(TypedDict):
    kind: str
    value: str


class LanguageString(TypedDict):
    language: str
    value: str


MarkedString: TypeAlias = str | LanguageString
HoverContents: TypeAlias = MarkedString | MarkupContent | list[MarkedString]


class Hover(TypedDict):
    contents: HoverContents
    range: NotRequired[Range]


class Diagnostic(TypedDict):
    range: Range
    message: str
    severity: NotRequired[int]
    code: NotRequired[int | str]


class DocumentSymbol(TypedDict):
    name: str
    kind: int
    range: Range
    selectionRange: Range
    children: NotRequired[list["DocumentSymbol"]]


class LocationUri(TypedDict):
    uri: str


class WorkspaceSymbol(TypedDict):
    name: str
    kind: int
    location: Location | LocationUri


Symbol: TypeAlias = DocumentSymbol | WorkspaceSymbol


class CallHierarchyItem(TypedDict):
    name: str
    kind: int
    uri: str
    range: Range
    selectionRange: Range


class FileEvent(TypedDict):
    uri: str
    type: int


class ResponseError(TypedDict):
    code: int
    message: str


class Message(TypedDict, total=False):
    jsonrpc: str
    id: int | str
    method: str
    params: LSPAny
    result: LSPAny
    error: ResponseError
