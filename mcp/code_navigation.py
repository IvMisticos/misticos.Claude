#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["mcp>=2"]
# ///

import atexit
from pathlib import Path

from mcp.server.mcpserver import MCPServer
from result_formatting import (
    Call,
    calls_text,
    diagnostics_text,
    hover_text,
    locations_text,
    symbols_text,
)
from server_registry import server_for, stop_all_servers
from text_positions import to_uri
from workspace_edits import apply_workspace_edit

mcp = MCPServer("code-navigation")


def resolved(file):
    path = Path(file).expanduser().resolve()
    if not path.is_file():
        raise ValueError(f"{file} is not a file")
    return path


async def server_at(file):
    path = resolved(file)
    return path, await server_for(path)


async def at_position(method, file, line, column, extra=None):
    path, server = await server_at(file)
    return await server.at_position(method, path, line, column, extra)


async def about_document(method, path, server):
    server.open_document(path)
    return await server.request(method, {"textDocument": {"uri": to_uri(path)}})


@mcp.tool()
async def definition(file: str, line: int, column: int) -> str:
    """Where the symbol at file:line:column (1-based) is defined."""
    return locations_text(
        await at_position("textDocument/definition", file, line, column)
    )


@mcp.tool()
async def references(file: str, line: int, column: int) -> str:
    """Every reference to the symbol at file:line:column (1-based), including its declaration."""
    return locations_text(
        await at_position(
            "textDocument/references",
            file,
            line,
            column,
            {"context": {"includeDeclaration": True}},
        )
    )


@mcp.tool()
async def hover(file: str, line: int, column: int) -> str:
    """Type and documentation of the symbol at file:line:column (1-based)."""
    return hover_text(await at_position("textDocument/hover", file, line, column))


@mcp.tool()
async def rename(file: str, line: int, column: int, new_name: str) -> str:
    """Rename the symbol at file:line:column (1-based) across the project and write the files."""
    edit = await at_position(
        "textDocument/rename", file, line, column, {"newName": new_name}
    )
    if not edit:
        return "nothing to rename"
    return "changed:\n" + "\n".join(apply_workspace_edit(edit))


@mcp.tool()
async def document_symbols(file: str) -> str:
    """Outline of a file: classes, functions, methods, fields, with positions."""
    path, server = await server_at(file)
    return symbols_text(
        await about_document("textDocument/documentSymbol", path, server)
    )


@mcp.tool()
async def workspace_symbols(query: str, file_in_project: str) -> str:
    """Symbols matching query across the project that contains file_in_project; that file picks the language."""
    _, server = await server_at(file_in_project)
    return symbols_text(await server.request("workspace/symbol", {"query": query}))


@mcp.tool()
async def diagnostics(file: str) -> str:
    """Compile errors and warnings in a file, without building the project."""
    path, server = await server_at(file)
    report = await about_document("textDocument/diagnostic", path, server)
    return diagnostics_text(path, report["items"])


CALL_DIRECTIONS = {
    "incoming": ("callHierarchy/incomingCalls", "from"),
    "outgoing": ("callHierarchy/outgoingCalls", "to"),
}


async def hierarchy_calls(direction, file, line, column):
    method, other_end = CALL_DIRECTIONS[direction]
    path, server = await server_at(file)
    functions = await server.at_position(
        "textDocument/prepareCallHierarchy", path, line, column
    )
    if not functions:
        raise ValueError(f"no function at {path}:{line}:{column}")
    calls = []
    for function in functions:
        for call in await server.request(method, {"item": function}) or []:
            call_site_owner = call.get("from", function)
            calls.append(
                Call(call[other_end], call_site_owner["uri"], call["fromRanges"])
            )
    return calls_text(calls)


@mcp.tool()
async def callers(file: str, line: int, column: int) -> str:
    """Functions that call the function at file:line:column (1-based), each with the places it calls from."""
    return await hierarchy_calls("incoming", file, line, column)


@mcp.tool()
async def callees(file: str, line: int, column: int) -> str:
    """Functions that the function at file:line:column (1-based) calls, each with the places it is called."""
    return await hierarchy_calls("outgoing", file, line, column)


if __name__ == "__main__":
    atexit.register(stop_all_servers)
    mcp.run()
