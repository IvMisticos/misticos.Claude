#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = ["mcp>=2"]
# [tool.ty.environment]
# root = ["."]
# python = "../.venv"
# ///

import atexit
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path

from lsp_client import LanguageServer
from lsp_methods import (
    DEFINITION,
    DIAGNOSTICS,
    DOCUMENT_SYMBOLS,
    HOVER,
    INCOMING_CALLS,
    OUTGOING_CALLS,
    PREPARE_CALL_HIERARCHY,
    REFERENCES,
    RENAME,
    WORKSPACE_SYMBOLS,
    Method,
)
from lsp_types import CallHierarchyItem, LSPAny
from mcp.server.mcpserver import MCPServer
from open_documents import Document, read_document
from result_formatting import (
    Call,
    calls_text,
    diagnostics_text,
    document_symbols_text,
    hover_text,
    locations_text,
    workspace_symbols_text,
)
from server_registry import server_for, stop_all_servers
from workspace_edits import apply_workspace_edit

type ServerFor = Callable[[Path], Awaitable[LanguageServer]]
type Tool = Callable[..., Awaitable[str]]


def resolved(file: str) -> Path:
    path = Path(file).expanduser().resolve()
    if not path.is_file():
        raise ValueError(f"{file} is not a file")
    return path


async def about_document[Result](
    method: Method[Result], document: Document, server: LanguageServer
) -> Result:
    params = {"textDocument": {"uri": document.path.as_uri()}}
    return await server.ask_about(document, method, params)


class CodeNavigation:
    def __init__(self, server_for: ServerFor) -> None:
        self.server_for = server_for

    def tools(self) -> list[Tool]:
        return [
            self.definition,
            self.references,
            self.hover,
            self.rename,
            self.document_symbols,
            self.workspace_symbols,
            self.diagnostics,
            self.callers,
            self.callees,
        ]

    async def document_and_server(self, file: str) -> tuple[Document, LanguageServer]:
        document = read_document(resolved(file))
        return document, await self.server_for(document.path)

    async def at_position[Result](
        self,
        method: Method[Result],
        file: str,
        line: int,
        column: int,
        extra: Mapping[str, LSPAny] | None = None,
    ) -> Result:
        document, server = await self.document_and_server(file)
        return await server.at_position(method, document, line, column, extra)

    async def definition(self, file: str, line: int, column: int) -> str:
        """Where the symbol at file:line:column (1-based) is defined."""
        return locations_text(await self.at_position(DEFINITION, file, line, column))

    async def references(self, file: str, line: int, column: int) -> str:
        """Every reference to the symbol at file:line:column (1-based), including its declaration."""
        return locations_text(
            await self.at_position(
                REFERENCES,
                file,
                line,
                column,
                {"context": {"includeDeclaration": True}},
            )
        )

    async def hover(self, file: str, line: int, column: int) -> str:
        """Type and documentation of the symbol at file:line:column (1-based)."""
        return hover_text(await self.at_position(HOVER, file, line, column))

    async def rename(self, file: str, line: int, column: int, new_name: str) -> str:
        """Rename the symbol at file:line:column (1-based) across the project and write the files."""
        edit = await self.at_position(RENAME, file, line, column, {"newName": new_name})
        if not edit:
            return "nothing to rename"
        return "changed:\n" + "\n".join(apply_workspace_edit(edit))

    async def document_symbols(self, file: str) -> str:
        """Outline of a file: classes, functions, methods, fields, with positions."""
        document, server = await self.document_and_server(file)
        symbols = await about_document(DOCUMENT_SYMBOLS, document, server)
        return document_symbols_text(document.path, symbols)

    async def workspace_symbols(self, query: str, file_in_project: str) -> str:
        """Symbols matching query across the project that contains file_in_project; that file picks the language."""
        document, server = await self.document_and_server(file_in_project)
        return workspace_symbols_text(
            await server.ask_about(document, WORKSPACE_SYMBOLS, {"query": query})
        )

    async def diagnostics(self, file: str) -> str:
        """Compile errors and warnings in a file, without building the project."""
        document, server = await self.document_and_server(file)
        report = await about_document(DIAGNOSTICS, document, server)
        return diagnostics_text(document.path, report["items"])

    async def callers(self, file: str, line: int, column: int) -> str:
        """Functions that call the function at file:line:column (1-based), each with the places it calls from."""
        server, functions = await self.functions_at(file, line, column)
        calls = [
            Call(call["from"], call["from"]["uri"], call["fromRanges"])
            for function in functions
            for call in await server.request(INCOMING_CALLS, {"item": function}) or []
        ]
        return calls_text(calls)

    async def callees(self, file: str, line: int, column: int) -> str:
        """Functions that the function at file:line:column (1-based) calls, each with the places it is called."""
        server, functions = await self.functions_at(file, line, column)
        calls = [
            Call(call["to"], function["uri"], call["fromRanges"])
            for function in functions
            for call in await server.request(OUTGOING_CALLS, {"item": function}) or []
        ]
        return calls_text(calls)

    async def functions_at(
        self, file: str, line: int, column: int
    ) -> tuple[LanguageServer, list[CallHierarchyItem]]:
        document, server = await self.document_and_server(file)
        functions = await server.at_position(
            PREPARE_CALL_HIERARCHY, document, line, column
        )
        if not functions:
            raise ValueError(f"no function at {document.path}:{line}:{column}")
        return server, functions


if __name__ == "__main__":
    atexit.register(stop_all_servers)
    mcp = MCPServer("code-navigation")
    for tool in CodeNavigation(server_for).tools():
        mcp.add_tool(tool)
    mcp.run()
