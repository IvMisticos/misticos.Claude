#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["mcp>=2"]
# ///

import asyncio
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse
from urllib.request import pathname2url

from mcp.server.mcpserver import MCPServer

LANGUAGE_SERVERS = {
    "typescript": {
        "command": ["tsgo", "--lsp", "-stdio"],
        "extensions": {".ts": "typescript", ".tsx": "typescriptreact", ".mts": "typescript", ".cts": "typescript", ".js": "javascript", ".jsx": "javascriptreact", ".mjs": "javascript", ".cjs": "javascript"},
    },
    "csharp": {"command": ["csharp-ls"], "extensions": {".cs": "csharp"}},
    "python": {"command": ["ty", "server"], "extensions": {".py": "python", ".pyi": "python"}},
}
EXTENSION_TO_SERVER = {
    extension: name for name, server in LANGUAGE_SERVERS.items() for extension in server["extensions"]
}
TOOLCHAIN_BIN_DIRS = (".local/bin", ".bun/bin", ".dotnet/tools", ".dotnet")
QUIET_SECONDS_BEFORE_READY = 2.0
MAX_STARTUP_SECONDS = 90.0
REQUEST_TIMEOUT_SECONDS = 60.0
LINE_BREAK = re.compile(r"\r\n|\r|\n")

mcp = MCPServer("code-navigation")


def toolchain_environment():
    home = Path.home()
    environment = dict(os.environ)
    bin_dirs = [str(home / directory) for directory in TOOLCHAIN_BIN_DIRS]
    environment["PATH"] = os.pathsep.join([*bin_dirs, environment.get("PATH", "")])
    environment.setdefault("DOTNET_ROOT", str(home / ".dotnet"))
    return environment


def to_uri(path):
    return "file://" + pathname2url(str(path))


def from_uri(uri):
    return Path(unquote(urlparse(uri).path))


def project_root(path):
    try:
        output = subprocess.run(
            ["git", "-C", str(path.parent), "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        return Path(output)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return Path.cwd()


class LanguageServerExited(RuntimeError):
    pass


class LanguageServer:
    def __init__(self, name, root):
        self.name = name
        self.root = root
        self.process = None
        self.pending = {}
        self.next_id = 1
        self.opened = {}
        self.last_message_at = 0.0
        self.reader_task = None

    @property
    def alive(self):
        return self.process is not None and self.process.returncode is None and not self.reader_task.done()

    async def start(self):
        spec = LANGUAGE_SERVERS[self.name]
        self.process = await asyncio.create_subprocess_exec(
            *spec["command"], cwd=self.root, env=toolchain_environment(),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=sys.stderr,
        )
        self.reader_task = asyncio.create_task(self.read_messages())
        try:
            await self.request("initialize", {
                "processId": os.getpid(),
                "rootUri": to_uri(self.root),
                "workspaceFolders": [{"uri": to_uri(self.root), "name": self.root.name}],
                "capabilities": {
                    "window": {"workDoneProgress": True},
                    "workspace": {"workspaceEdit": {"documentChanges": True}},
                    "textDocument": {"hover": {"contentFormat": ["markdown", "plaintext"]}},
                },
            })
            self.notify("initialized", {})
            await self.wait_until_quiet()
        except Exception:
            self.stop()
            raise

    def stop(self):
        if self.process is not None and self.process.returncode is None:
            self.process.kill()
        if self.reader_task is not None:
            self.reader_task.cancel()
        self.fail_pending(LanguageServerExited(f"{self.name} language server exited"))

    async def wait_until_quiet(self):
        started = asyncio.get_event_loop().time()
        while asyncio.get_event_loop().time() - started < MAX_STARTUP_SECONDS:
            await asyncio.sleep(0.25)
            if asyncio.get_event_loop().time() - self.last_message_at >= QUIET_SECONDS_BEFORE_READY:
                return

    def send(self, message):
        body = json.dumps(message).encode()
        self.process.stdin.write(b"Content-Length: %d\r\n\r\n" % len(body) + body)

    def notify(self, method, params):
        self.send({"jsonrpc": "2.0", "method": method, "params": params})

    async def request(self, method, params):
        if not self.alive:
            raise LanguageServerExited(f"{self.name} language server exited")
        request_id = self.next_id
        self.next_id += 1
        future = asyncio.get_event_loop().create_future()
        self.pending[request_id] = future
        self.send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        try:
            return await asyncio.wait_for(future, REQUEST_TIMEOUT_SECONDS)
        finally:
            self.pending.pop(request_id, None)

    async def read_messages(self):
        try:
            while True:
                message = await self.read_message()
                self.last_message_at = asyncio.get_event_loop().time()
                self.dispatch(message)
        except (asyncio.IncompleteReadError, ValueError, TypeError, ConnectionError):
            pass
        finally:
            self.fail_pending(LanguageServerExited(f"{self.name} language server exited"))

    async def read_message(self):
        length = None
        while True:
            line = await self.process.stdout.readline()
            if not line:
                raise asyncio.IncompleteReadError(line, None)
            if line.lower().startswith(b"content-length:"):
                length = int(line.split(b":")[1])
            if line in (b"\r\n", b"\n"):
                break
        return json.loads(await self.process.stdout.readexactly(length))

    def fail_pending(self, error):
        for future in self.pending.values():
            if not future.done():
                future.set_exception(error)
        self.pending.clear()

    def dispatch(self, message):
        if "id" in message and "method" not in message:
            future = self.pending.pop(message["id"], None)
            if future is None or future.done():
                return
            if "error" in message:
                future.set_exception(RuntimeError(message["error"].get("message", "language server error")))
            else:
                future.set_result(message.get("result"))
            return
        if "id" in message:
            self.answer_server_request(message)

    def answer_server_request(self, message):
        result = None
        if message["method"] == "workspace/configuration":
            result = [None for _ in message.get("params", {}).get("items", [])]
        if message["method"] == "workspace/applyEdit":
            result = {"applied": False}
        self.send({"jsonrpc": "2.0", "id": message["id"], "result": result})

    def open_document(self, path):
        text = read_text(path)
        uri = to_uri(path)
        language_id = LANGUAGE_SERVERS[self.name]["extensions"][path.suffix]
        if uri not in self.opened:
            self.opened[uri] = (1, text)
            self.notify("textDocument/didOpen", {"textDocument": {"uri": uri, "languageId": language_id, "version": 1, "text": text}})
            return text
        version, known_text = self.opened[uri]
        if text == known_text:
            return text
        self.opened[uri] = (version + 1, text)
        self.notify("textDocument/didChange", {"textDocument": {"uri": uri, "version": version + 1}, "contentChanges": [{"text": text}]})
        return text

    async def at_position(self, method, path, line, column, extra=None):
        text = self.open_document(path)
        lines = LINE_BREAK.split(text)
        line_text = lines[line - 1] if 0 < line <= len(lines) else ""
        position = {"line": line - 1, "character": utf16_length(line_text[: column - 1])}
        params = {"textDocument": {"uri": to_uri(path)}, "position": position}
        params.update(extra or {})
        return await self.request(method, params)


def utf16_length(text):
    return len(text.encode("utf-16-le")) // 2


def utf16_offset_to_index(line_text, utf16_offset):
    units = 0
    for index, character in enumerate(line_text):
        if units >= utf16_offset:
            return index
        units += utf16_length(character)
    return len(line_text)


def read_text(path):
    with open(path, encoding="utf-8", errors="replace", newline="") as file:
        return file.read()


starting_servers = {}


async def start_server(name, root):
    server = LanguageServer(name, root)
    await server.start()
    return server


async def server_for(path):
    name = EXTENSION_TO_SERVER.get(path.suffix)
    if name is None:
        raise ValueError(f"no language server for {path.suffix} files")
    key = (name, project_root(path))
    starting = starting_servers.get(key)
    if starting is not None and starting.done() and (starting.exception() or not starting.result().alive):
        starting = None
    if starting is None:
        starting = starting_servers[key] = asyncio.ensure_future(start_server(*key))
    return await starting


def resolved(file):
    path = Path(file).expanduser().resolve()
    if not path.is_file():
        raise ValueError(f"{file} is not a file")
    return path


def location_line(location):
    uri = location.get("targetUri") or location.get("uri")
    range_ = location.get("targetSelectionRange") or location.get("range")
    path = from_uri(uri)
    if range_ is None:
        return str(path)
    return f"{path}:{position_text(path, range_['start'])}"


def position_text(path, position):
    try:
        lines = LINE_BREAK.split(read_text(path))
        line_text = lines[position["line"]]
    except (OSError, IndexError):
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
    return "\n".join(part if isinstance(part, str) else part.get("value", "") for part in contents)


def symbols_text(result):
    lines = symbol_lines(result or [], 0)
    return "\n".join(lines) or "no symbols"


def symbol_lines(symbols, indent):
    lines = []
    for symbol in symbols:
        lines.append(f"{'  ' * indent}{symbol['name']} ({symbol_kind(symbol.get('kind'))}) {symbol_place(symbol)}")
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


SYMBOL_KINDS = {1: "file", 2: "module", 3: "namespace", 4: "package", 5: "class", 6: "method", 7: "property", 8: "field", 9: "constructor", 10: "enum", 11: "interface", 12: "function", 13: "variable", 14: "constant", 15: "string", 16: "number", 17: "boolean", 18: "array", 19: "object", 20: "key", 21: "null", 22: "enum member", 23: "struct", 24: "event", 25: "operator", 26: "type parameter"}


def symbol_kind(kind):
    return SYMBOL_KINDS.get(kind, "symbol")


def apply_workspace_edit(edit):
    changed = []
    for uri, edits in (edit.get("changes") or {}).items():
        changed.append(apply_text_edits(from_uri(uri), edits))
    for change in edit.get("documentChanges") or []:
        if "textDocument" not in change:
            raise ValueError(f"the language server wants a file operation ({change.get('kind')}) that this tool does not apply; nothing was written")
    for change in edit.get("documentChanges") or []:
        changed.append(apply_text_edits(from_uri(change["textDocument"]["uri"]), change["edits"]))
    return changed


def apply_text_edits(path, edits):
    text = read_text(path)
    lines = LINE_BREAK.split(text)
    offsets = line_offsets(text)
    for edit in sorted(edits, key=lambda e: (e["range"]["start"]["line"], e["range"]["start"]["character"]), reverse=True):
        start = text_offset(lines, offsets, edit["range"]["start"])
        end = text_offset(lines, offsets, edit["range"]["end"])
        text = text[:start] + edit["newText"] + text[end:]
    with open(path, "w", encoding="utf-8", newline="") as file:
        file.write(text)
    return str(path)


def text_offset(lines, offsets, position):
    return offsets[position["line"]] + utf16_offset_to_index(lines[position["line"]], position["character"])


def line_offsets(text):
    offsets = [0]
    for match in LINE_BREAK.finditer(text):
        offsets.append(match.end())
    return offsets


@mcp.tool()
async def definition(file: str, line: int, column: int) -> str:
    """Where the symbol at file:line:column (1-based) is defined."""
    path = resolved(file)
    server = await server_for(path)
    return locations_text(await server.at_position("textDocument/definition", path, line, column))


@mcp.tool()
async def references(file: str, line: int, column: int) -> str:
    """Every reference to the symbol at file:line:column (1-based), including its declaration."""
    path = resolved(file)
    server = await server_for(path)
    result = await server.at_position("textDocument/references", path, line, column, {"context": {"includeDeclaration": True}})
    return locations_text(result)


@mcp.tool()
async def hover(file: str, line: int, column: int) -> str:
    """Type and documentation of the symbol at file:line:column (1-based)."""
    path = resolved(file)
    server = await server_for(path)
    return hover_text(await server.at_position("textDocument/hover", path, line, column))


@mcp.tool()
async def rename(file: str, line: int, column: int, new_name: str) -> str:
    """Rename the symbol at file:line:column (1-based) across the project and write the files."""
    path = resolved(file)
    server = await server_for(path)
    edit = await server.at_position("textDocument/rename", path, line, column, {"newName": new_name})
    if not edit:
        return "nothing to rename"
    return "changed:\n" + "\n".join(apply_workspace_edit(edit))


@mcp.tool()
async def document_symbols(file: str) -> str:
    """Outline of a file: classes, functions, methods, fields, with positions."""
    path = resolved(file)
    server = await server_for(path)
    server.open_document(path)
    return symbols_text(await server.request("textDocument/documentSymbol", {"textDocument": {"uri": to_uri(path)}}))


@mcp.tool()
async def workspace_symbols(query: str, file_in_project: str) -> str:
    """Symbols matching query across the project that contains file_in_project; that file picks the language."""
    path = resolved(file_in_project)
    server = await server_for(path)
    return symbols_text(await server.request("workspace/symbol", {"query": query}))


if __name__ == "__main__":
    mcp.run()
