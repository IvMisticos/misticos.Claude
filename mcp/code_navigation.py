#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = ["mcp>=2"]
# [tool.ty.environment]
# root = ["."]
# python = "../.venv"
# ///

import atexit
from collections.abc import Awaitable, Callable
from pathlib import Path

from lsp_client import LanguageServer
from lsp_types import LSPAny
from mcp.server.mcpserver import MCPServer
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
from text_positions import to_uri
from workspace_edits import apply_workspace_edit

type ServerFor = Callable[[Path], Awaitable[LanguageServer]]
type Tool = Callable[..., Awaitable[str]]

CALL_DIRECTIONS = {
    "incoming": ("callHierarchy/incomingCalls", "from"),
    "outgoing": ("callHierarchy/outgoingCalls", "to"),
}


def resolved(file: str) -> Path:
    path = Path(file).expanduser().resolve()
    if not path.is_file():
        raise ValueError(f"{file} is not a file")
    return path


async def about_document(method: str, path: Path, server: LanguageServer) -> LSPAny:
    return await server.ask_about(path, method, {"textDocument": {"uri": to_uri(path)}})


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

    async def server_at(self, file: str) -> tuple[Path, LanguageServer]:
        path = resolved(file)
        return path, await self.server_for(path)

    async def at_position(
        self,
        method: str,
        file: str,
        line: int,
        column: int,
        extra: dict[str, LSPAny] | None = None,
    ) -> LSPAny:
        path, server = await self.server_at(file)
        return await server.at_position(method, path, line, column, extra)

    async def definition(self, file: str, line: int, column: int) -> str:
        """Where the symbol at file:line:column (1-based) is defined."""
        return locations_text(
            await self.at_position("textDocument/definition", file, line, column)
        )

    async def references(self, file: str, line: int, column: int) -> str:
        """Every reference to the symbol at file:line:column (1-based), including its declaration."""
        return locations_text(
            await self.at_position(
                "textDocument/references",
                file,
                line,
                column,
                {"context": {"includeDeclaration": True}},
            )
        )

    async def hover(self, file: str, line: int, column: int) -> str:
        """Type and documentation of the symbol at file:line:column (1-based)."""
        return hover_text(
            await self.at_position("textDocument/hover", file, line, column)
        )

    async def rename(self, file: str, line: int, column: int, new_name: str) -> str:
        """Rename the symbol at file:line:column (1-based) across the project and write the files."""
        edit = await self.at_position(
            "textDocument/rename", file, line, column, {"newName": new_name}
        )
        if not edit:
            return "nothing to rename"
        return "changed:\n" + "\n".join(apply_workspace_edit(edit))

    async def document_symbols(self, file: str) -> str:
        """Outline of a file: classes, functions, methods, fields, with positions."""
        path, server = await self.server_at(file)
        return document_symbols_text(
            path, await about_document("textDocument/documentSymbol", path, server)
        )

    async def workspace_symbols(self, query: str, file_in_project: str) -> str:
        """Symbols matching query across the project that contains file_in_project; that file picks the language."""
        path, server = await self.server_at(file_in_project)
        return workspace_symbols_text(
            await server.ask_about(path, "workspace/symbol", {"query": query})
        )

    async def diagnostics(self, file: str) -> str:
        """Compile errors and warnings in a file, without building the project."""
        path, server = await self.server_at(file)
        report = await about_document("textDocument/diagnostic", path, server)
        return diagnostics_text(path, report["items"])

    async def callers(self, file: str, line: int, column: int) -> str:
        """Functions that call the function at file:line:column (1-based), each with the places it calls from."""
        return await self.hierarchy_calls("incoming", file, line, column)

    async def callees(self, file: str, line: int, column: int) -> str:
        """Functions that the function at file:line:column (1-based) calls, each with the places it is called."""
        return await self.hierarchy_calls("outgoing", file, line, column)

    async def hierarchy_calls(
        self, direction: str, file: str, line: int, column: int
    ) -> str:
        method, other_end = CALL_DIRECTIONS[direction]
        path, server = await self.server_at(file)
        functions = await server.at_position(
            "textDocument/prepareCallHierarchy", path, line, column
        )
        if not functions:
            raise ValueError(f"no function at {path}:{line}:{column}")
        calls: list[Call] = []
        for function in functions:
            for call in await server.ask_about(path, method, {"item": function}) or []:
                call_site_owner = call.get("from", function)
                calls.append(
                    Call(call[other_end], call_site_owner["uri"], call["fromRanges"])
                )
        return calls_text(calls)


if __name__ == "__main__":
    atexit.register(stop_all_servers)
    mcp = MCPServer("code-navigation")
    for tool in CodeNavigation(server_for).tools():
        mcp.add_tool(tool)
    mcp.run()
