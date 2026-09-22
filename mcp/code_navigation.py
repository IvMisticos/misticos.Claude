#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["mcp>=2"]
# ///

import atexit
from pathlib import Path

from mcp.server.mcpserver import MCPServer
from result_formatting import hover_text, locations_text, symbols_text
from server_registry import server_for, stop_all_servers
from text_positions import to_uri
from workspace_edits import apply_workspace_edit

mcp = MCPServer("code-navigation")


def resolved(file):
    path = Path(file).expanduser().resolve()
    if not path.is_file():
        raise ValueError(f"{file} is not a file")
    return path


@mcp.tool()
async def definition(file: str, line: int, column: int) -> str:
    """Where the symbol at file:line:column (1-based) is defined."""
    path = resolved(file)
    server = await server_for(path)
    return locations_text(
        await server.at_position("textDocument/definition", path, line, column)
    )


@mcp.tool()
async def references(file: str, line: int, column: int) -> str:
    """Every reference to the symbol at file:line:column (1-based), including its declaration."""
    path = resolved(file)
    server = await server_for(path)
    result = await server.at_position(
        "textDocument/references",
        path,
        line,
        column,
        {"context": {"includeDeclaration": True}},
    )
    return locations_text(result)


@mcp.tool()
async def hover(file: str, line: int, column: int) -> str:
    """Type and documentation of the symbol at file:line:column (1-based)."""
    path = resolved(file)
    server = await server_for(path)
    return hover_text(
        await server.at_position("textDocument/hover", path, line, column)
    )


@mcp.tool()
async def rename(file: str, line: int, column: int, new_name: str) -> str:
    """Rename the symbol at file:line:column (1-based) across the project and write the files."""
    path = resolved(file)
    server = await server_for(path)
    edit = await server.at_position(
        "textDocument/rename", path, line, column, {"newName": new_name}
    )
    if not edit:
        return "nothing to rename"
    return "changed:\n" + "\n".join(apply_workspace_edit(edit))


@mcp.tool()
async def document_symbols(file: str) -> str:
    """Outline of a file: classes, functions, methods, fields, with positions."""
    path = resolved(file)
    server = await server_for(path)
    server.open_document(path)
    return symbols_text(
        await server.request(
            "textDocument/documentSymbol", {"textDocument": {"uri": to_uri(path)}}
        )
    )


@mcp.tool()
async def workspace_symbols(query: str, file_in_project: str) -> str:
    """Symbols matching query across the project that contains file_in_project; that file picks the language."""
    path = resolved(file_in_project)
    server = await server_for(path)
    return symbols_text(await server.request("workspace/symbol", {"query": query}))


if __name__ == "__main__":
    atexit.register(stop_all_servers)
    mcp.run()
