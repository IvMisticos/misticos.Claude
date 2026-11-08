from dataclasses import dataclass

from lsp_types import (
    CallHierarchyIncomingCall,
    CallHierarchyItem,
    CallHierarchyOutgoingCall,
    DocumentSymbol,
    FullDocumentDiagnosticReport,
    Hover,
    Location,
    LocationLink,
    WorkspaceEdit,
    WorkspaceSymbol,
)
from pydantic import TypeAdapter


@dataclass(frozen=True)
class Method[Result]:
    name: str
    result: TypeAdapter[Result]


INITIALIZE = Method("initialize", TypeAdapter(object))
DEFINITION = Method(
    "textDocument/definition",
    TypeAdapter(Location | list[Location] | list[LocationLink] | None),
)
REFERENCES = Method("textDocument/references", TypeAdapter(list[Location] | None))
HOVER = Method("textDocument/hover", TypeAdapter(Hover | None))
RENAME = Method("textDocument/rename", TypeAdapter(WorkspaceEdit | None))
DOCUMENT_SYMBOLS = Method(
    "textDocument/documentSymbol",
    TypeAdapter(list[DocumentSymbol] | list[WorkspaceSymbol] | None),
)
WORKSPACE_SYMBOLS = Method(
    "workspace/symbol", TypeAdapter(list[WorkspaceSymbol] | None)
)
DIAGNOSTICS = Method(
    "textDocument/diagnostic", TypeAdapter(FullDocumentDiagnosticReport)
)
PREPARE_CALL_HIERARCHY = Method(
    "textDocument/prepareCallHierarchy", TypeAdapter(list[CallHierarchyItem] | None)
)
INCOMING_CALLS = Method(
    "callHierarchy/incomingCalls", TypeAdapter(list[CallHierarchyIncomingCall] | None)
)
OUTGOING_CALLS = Method(
    "callHierarchy/outgoingCalls", TypeAdapter(list[CallHierarchyOutgoingCall] | None)
)
