import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

from text_positions import LINE_BREAK, read_text, to_uri, utf16_length

TOOLCHAIN_BIN_DIRS = (".local/bin", ".bun/bin", ".dotnet/tools", ".dotnet")
QUIET_SECONDS_BEFORE_READY = 2.0
MAX_STARTUP_SECONDS = 90.0
REQUEST_TIMEOUT_SECONDS = 60.0


def toolchain_environment():
    home = Path.home()
    environment = dict(os.environ)
    bin_dirs = [str(home / directory) for directory in TOOLCHAIN_BIN_DIRS]
    environment["PATH"] = os.pathsep.join([*bin_dirs, environment.get("PATH", "")])
    environment.setdefault("DOTNET_ROOT", str(home / ".dotnet"))
    return environment


class LanguageServerExited(RuntimeError):
    pass


class LanguageServer:
    def __init__(self, name, command, language_ids, root):
        self.name = name
        self.command = command
        self.language_ids = language_ids
        self.root = root
        self.process = None
        self.pending = {}
        self.next_id = 1
        self.opened = {}
        self.last_message_at = 0.0
        self.reader_task = None

    @property
    def alive(self):
        return (
            self.process is not None
            and self.process.returncode is None
            and not self.reader_task.done()
        )

    async def start(self):
        self.process = await asyncio.create_subprocess_exec(
            *self.command,
            cwd=self.root,
            env=toolchain_environment(),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=sys.stderr,
        )
        self.reader_task = asyncio.create_task(self.read_messages())
        try:
            await self.request(
                "initialize",
                {
                    "processId": os.getpid(),
                    "rootUri": to_uri(self.root),
                    "workspaceFolders": [
                        {"uri": to_uri(self.root), "name": self.root.name}
                    ],
                    "capabilities": {
                        "window": {"workDoneProgress": True},
                        "workspace": {"workspaceEdit": {"documentChanges": True}},
                        "textDocument": {
                            "hover": {"contentFormat": ["markdown", "plaintext"]}
                        },
                    },
                },
            )
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
            if (
                asyncio.get_event_loop().time() - self.last_message_at
                >= QUIET_SECONDS_BEFORE_READY
            ):
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
        self.send(
            {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        )
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
            self.fail_pending(
                LanguageServerExited(f"{self.name} language server exited")
            )

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
                future.set_exception(
                    RuntimeError(
                        message["error"].get("message", "language server error")
                    )
                )
            else:
                future.set_result(message.get("result"))
            return
        if "id" in message:
            self.answer_server_request(message)

    def answer_server_request(self, message):
        method = message["method"]
        if method == "workspace/configuration":
            result = [None for _ in message.get("params", {}).get("items", [])]
        elif method == "workspace/applyEdit":
            result = {"applied": False}
        elif method.startswith(("window/workDoneProgress", "client/")):
            result = None
        else:
            self.send(
                {
                    "jsonrpc": "2.0",
                    "id": message["id"],
                    "error": {"code": -32601, "message": f"{method} is not supported"},
                }
            )
            return
        self.send({"jsonrpc": "2.0", "id": message["id"], "result": result})

    def open_document(self, path):
        text = read_text(path)
        uri = to_uri(path)
        language_id = self.language_ids[path.suffix]
        if uri not in self.opened:
            self.opened[uri] = (1, text)
            self.notify(
                "textDocument/didOpen",
                {
                    "textDocument": {
                        "uri": uri,
                        "languageId": language_id,
                        "version": 1,
                        "text": text,
                    }
                },
            )
            return text
        version, known_text = self.opened[uri]
        if text == known_text:
            return text
        self.opened[uri] = (version + 1, text)
        self.notify(
            "textDocument/didChange",
            {
                "textDocument": {"uri": uri, "version": version + 1},
                "contentChanges": [{"text": text}],
            },
        )
        return text

    async def at_position(self, method, path, line, column, extra=None):
        text = self.open_document(path)
        lines = LINE_BREAK.split(text)
        line_text = lines[line - 1] if 0 < line <= len(lines) else ""
        position = {
            "line": line - 1,
            "character": utf16_length(line_text[: column - 1]),
        }
        params = {"textDocument": {"uri": to_uri(path)}, "position": position}
        params.update(extra or {})
        return await self.request(method, params)
