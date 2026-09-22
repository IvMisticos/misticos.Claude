#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["mcp>=2"]
# ///

import asyncio
import atexit
import os
import subprocess
from pathlib import Path

from lsp_client import LanguageServer
from mcp.server.mcpserver import MCPServer
from text_positions import (
    apply_workspace_edit,
    from_uri,
    lines_of,
    to_uri,
    utf16_offset_to_index,
)

LANGUAGE_SERVERS = {
    "typescript": {
        "command": ["tsgo", "--lsp", "-stdio"],
        "extensions": {
            ".ts": "typescript",
            ".tsx": "typescriptreact",
            ".mts": "typescript",
            ".cts": "typescript",
            ".js": "javascript",
            ".jsx": "javascriptreact",
            ".mjs": "javascript",
            ".cjs": "javascript",
        },
    },
    "csharp": {"command": ["csharp-ls"], "extensions": {".cs": "csharp"}},
    "python": {
        "command": ["ty", "server"],
        "extensions": {".py": "python", ".pyi": "python"},
    },
}
EXTENSION_TO_SERVER = {
    extension: name
    for name, server in LANGUAGE_SERVERS.items()
    for extension in server["extensions"]
}
mcp = MCPServer("code-navigation")
SOLUTION_SUFFIXES = (".sln", ".slnx", ".slnf")
PROJECT_SUFFIXES = (".csproj",)
SKIPPED_DIRECTORIES = {"bin", "obj", "node_modules"}


def git_root(path):
    try:
        output = subprocess.run(
            ["git", "-C", str(path.parent), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        return Path(output)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return Path.cwd()


def holds_file_with(directory, suffixes):
    try:
        return any(child.suffix in suffixes for child in directory.iterdir())
    except OSError:
        return False


def nearest_directory_with(path, suffixes, repo):
    if repo not in path.parents:
        return None
    for directory in path.parents:
        if holds_file_with(directory, suffixes):
            return directory
        if directory == repo:
            return None
    return None


def solution_files_under(repo):
    found = []
    for directory, subdirectories, files in os.walk(repo):
        subdirectories[:] = [
            name
            for name in subdirectories
            if not name.startswith(".") and name not in SKIPPED_DIRECTORIES
        ]
        found.extend(
            Path(directory) / name
            for name in files
            if Path(name).suffix in SOLUTION_SUFFIXES
        )
    return found


def solution_mentioning(project_file, repo):
    for solution in solution_files_under(repo):
        try:
            if project_file.name in solution.read_text(
                encoding="utf-8", errors="replace"
            ):
                return solution.parent
        except OSError:
            continue
    return None


def nearest_project_file(path, repo):
    directory = nearest_directory_with(path, PROJECT_SUFFIXES, repo)
    if directory is None:
        return None
    return next(
        child for child in directory.iterdir() if child.suffix in PROJECT_SUFFIXES
    )


def csharp_root(path, repo):
    nearest_solution = nearest_directory_with(path, SOLUTION_SUFFIXES, repo)
    if nearest_solution is not None:
        return nearest_solution
    project_file = nearest_project_file(path, repo)
    if project_file is None:
        return repo
    return solution_mentioning(project_file, repo) or project_file.parent


def project_root(name, path):
    repo = git_root(path)
    if name != "csharp":
        return repo
    return csharp_root(path, repo)


starting_servers = {}


async def start_server(name, root):
    spec = LANGUAGE_SERVERS[name]
    server = LanguageServer(name, spec["command"], spec["extensions"], root)
    await server.start()
    return server


async def server_for(path):
    name = EXTENSION_TO_SERVER.get(path.suffix)
    if name is None:
        raise ValueError(f"no language server for {path.suffix} files")
    key = (name, project_root(name, path))
    starting = starting_servers.get(key)
    if (
        starting is not None
        and starting.done()
        and (starting.exception() or not starting.result().alive)
    ):
        if not starting.exception():
            starting.result().stop()
        starting = None
    if starting is None:
        starting = starting_servers[key] = asyncio.ensure_future(start_server(*key))
    return await starting


def stop_all_servers():
    for starting in starting_servers.values():
        if starting.done() and not starting.exception():
            starting.result().stop()


def resolved(file):
    path = Path(file).expanduser().resolve()
    if not path.is_file():
        raise ValueError(f"{file} is not a file")
    return path


def location_line(location):
    uri = location.get("targetUri") or location.get("uri")
    if uri is None:
        return "unknown location"
    range_ = location.get("targetSelectionRange") or location.get("range")
    path = from_uri(uri)
    if range_ is None:
        return str(path)
    return f"{path}:{position_text(path, range_['start'])}"


def position_text(path, position):
    try:
        line_text = lines_of(path)[position["line"]]
    except (OSError, UnicodeDecodeError, IndexError):
        return f"{position['line'] + 1}:{position['character'] + 1}"
    return f"{position['line'] + 1}:{utf16_offset_to_index(line_text, position['character']) + 1}"


def locations_text(result):
    if not result:
        return "no results"
    items = result if isinstance(result, list) else [result]
    return "\n".join(location_line(item) for item in items)


def hover_text(result):
    if not result:
        return "no hover information"
    contents = result.get("contents")
    if not contents:
        return "no hover information"
    if isinstance(contents, str):
        return contents
    if isinstance(contents, dict):
        return contents.get("value", "")
    return "\n".join(
        part if isinstance(part, str) else part.get("value", "") for part in contents
    )


def symbols_text(result):
    lines = symbol_lines(result or [], 0)
    return "\n".join(lines) or "no symbols"


def symbol_lines(symbols, indent):
    lines = []
    for symbol in symbols:
        lines.append(
            f"{'  ' * indent}{symbol['name']} ({symbol_kind(symbol.get('kind'))}) {symbol_place(symbol)}"
        )
        lines.extend(symbol_lines(symbol.get("children") or [], indent + 1))
    return lines


def symbol_place(symbol):
    location = symbol.get("location") or {}
    path = from_uri(location["uri"]) if "uri" in location else None
    range_ = symbol.get("selectionRange") or location.get("range")
    if range_ is None:
        return str(path or "")
    if path is None:
        return f"{range_['start']['line'] + 1}:{range_['start']['character'] + 1}"
    return f"{path}:{position_text(path, range_['start'])}"


SYMBOL_KINDS = {
    1: "file",
    2: "module",
    3: "namespace",
    4: "package",
    5: "class",
    6: "method",
    7: "property",
    8: "field",
    9: "constructor",
    10: "enum",
    11: "interface",
    12: "function",
    13: "variable",
    14: "constant",
    15: "string",
    16: "number",
    17: "boolean",
    18: "array",
    19: "object",
    20: "key",
    21: "null",
    22: "enum member",
    23: "struct",
    24: "event",
    25: "operator",
    26: "type parameter",
}


def symbol_kind(kind):
    return SYMBOL_KINDS.get(kind, "symbol")


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
