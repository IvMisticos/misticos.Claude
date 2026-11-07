import asyncio
import json
import os
import pathlib
import subprocess
import sys
from collections.abc import Mapping

from lsp_methods import INITIALIZE, Method
from lsp_types import (
    FileEvent,
    LSPAny,
    Message,
    RequestId,
    Response,
    ResponseError,
)
from open_documents import Document, OpenDocuments
from text_positions import lsp_position

QUIET_SECONDS_BEFORE_READY = 2.0
MAX_STARTUP_SECONDS = 90.0
REQUEST_TIMEOUT_SECONDS = 60.0
METHOD_NOT_FOUND = -32601


class LanguageServerExited(RuntimeError):
    pass


class LanguageServer:
    @classmethod
    async def start(
        cls,
        name: str,
        command: list[str],
        language_ids: dict[str, str],
        root: pathlib.Path,
        environment: dict[str, str],
    ) -> "LanguageServer":
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=root,
            env=environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=sys.stderr,
        )
        server = cls(name, process, language_ids, root)
        try:
            await server.initialize()
            await server.wait_until_quiet()
        except Exception:
            server.stop()
            raise
        return server

    def __init__(
        self,
        name: str,
        process: asyncio.subprocess.Process,
        language_ids: dict[str, str],
        root: pathlib.Path,
    ) -> None:
        if process.stdin is None or process.stdout is None:
            raise ValueError(f"{name} language server needs piped stdin and stdout")
        self.name = name
        self.process = process
        self.stdin = process.stdin
        self.stdout = process.stdout
        self.root = root
        self.documents = OpenDocuments(language_ids, self.notify)
        self.pending: dict[RequestId, asyncio.Future[object]] = {}
        self.next_id = 1
        self.last_message_at = 0.0
        self.reader_task = asyncio.create_task(self.read_messages())

    @property
    def alive(self) -> bool:
        return self.process.returncode is None and not self.reader_task.done()

    async def initialize(self) -> None:
        await self.request(
            INITIALIZE,
            {
                "processId": os.getpid(),
                "rootUri": self.root.as_uri(),
                "workspaceFolders": [
                    {"uri": self.root.as_uri(), "name": self.root.name}
                ],
                "capabilities": {
                    "window": {"workDoneProgress": True},
                    "workspace": {"workspaceEdit": {"documentChanges": True}},
                    "textDocument": {
                        "hover": {"contentFormat": ["markdown", "plaintext"]},
                        "documentSymbol": {"hierarchicalDocumentSymbolSupport": True},
                        "diagnostic": {},
                        "callHierarchy": {},
                    },
                },
            },
        )
        self.notify("initialized", {})

    def stop(self) -> None:
        if self.process.returncode is None:
            self.process.kill()
        self.reader_task.cancel()
        self.fail_pending(self.exited())

    def exited(self) -> LanguageServerExited:
        return LanguageServerExited(f"{self.name} language server exited")

    async def wait_until_quiet(self) -> None:
        started = asyncio.get_event_loop().time()
        while asyncio.get_event_loop().time() - started < MAX_STARTUP_SECONDS:
            await asyncio.sleep(0.25)
            if (
                asyncio.get_event_loop().time() - self.last_message_at
                >= QUIET_SECONDS_BEFORE_READY
            ):
                return

    def send(self, message: Message) -> None:
        body = json.dumps(message).encode()
        self.stdin.write(b"Content-Length: %d\r\n\r\n" % len(body) + body)

    def notify(self, method: str, params: LSPAny) -> None:
        self.send({"jsonrpc": "2.0", "method": method, "params": params})

    async def request[Result](self, method: Method[Result], params: LSPAny) -> Result:
        if not self.alive:
            raise self.exited()
        request_id = self.next_id
        self.next_id += 1
        future = asyncio.get_event_loop().create_future()
        self.pending[request_id] = future
        self.send(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method.name,
                "params": params,
            }
        )
        try:
            result = await asyncio.wait_for(future, REQUEST_TIMEOUT_SECONDS)
        finally:
            self.pending.pop(request_id, None)
        return method.result.validate_python(result)

    async def read_messages(self) -> None:
        try:
            while True:
                message = await self.read_message()
                self.last_message_at = asyncio.get_event_loop().time()
                self.dispatch(message)
        except (asyncio.IncompleteReadError, ValueError, TypeError, ConnectionError):
            pass
        finally:
            self.fail_pending(self.exited())

    async def read_message(self) -> Message:
        length = None
        while True:
            line = await self.stdout.readline()
            if not line:
                raise asyncio.IncompleteReadError(line, None)
            if line.lower().startswith(b"content-length:"):
                length = int(line.split(b":")[1])
            if line in (b"\r\n", b"\n"):
                break
        if length is None:
            raise ValueError(f"{self.name} sent a message without Content-Length")
        return json.loads(await self.stdout.readexactly(length))

    def fail_pending(self, error: Exception) -> None:
        for future in self.pending.values():
            if not future.done():
                future.set_exception(error)
        self.pending.clear()

    def dispatch(self, message: Message) -> None:
        if "method" not in message:
            self.resolve_pending(message)
            return
        match message:
            case {"id": int() | str() as request_id, "method": str() as method}:
                self.answer_server_request(request_id, method, message.get("params"))

    def resolve_pending(self, response: Response) -> None:
        future = self.pending.pop(response["id"], None)
        if future is None or future.done():
            return
        if "error" in response:
            error = response["error"].get("message", "language server error")
            future.set_exception(RuntimeError(error))
            return
        future.set_result(response.get("result"))

    def answer_server_request(
        self, request_id: RequestId, method: str, params: LSPAny
    ) -> None:
        if method == "workspace/configuration":
            result = [None for _ in (params or {}).get("items", [])]
        elif method == "workspace/applyEdit":
            result = {"applied": False}
        elif method.startswith(("window/workDoneProgress", "client/")):
            result = None
        else:
            error: ResponseError = {
                "code": METHOD_NOT_FOUND,
                "message": f"{method} is not supported",
            }
            self.send({"jsonrpc": "2.0", "id": request_id, "error": error})
            return
        self.send({"jsonrpc": "2.0", "id": request_id, "result": result})

    def apply_file_changes(self, events: list[FileEvent]) -> None:
        if not events:
            return
        for event in events:
            self.documents.close(event["uri"])
        self.notify("workspace/didChangeWatchedFiles", {"changes": events})

    async def at_position[Result](
        self,
        method: Method[Result],
        document: Document,
        line: int,
        column: int,
        extra: Mapping[str, LSPAny] | None = None,
    ) -> Result:
        position = lsp_position(document.text, line, column)
        params = {"textDocument": {"uri": document.path.as_uri()}, "position": position}
        params.update(extra or {})
        return await self.ask_about(document, method, params)

    async def ask_about[Result](
        self, document: Document, method: Method[Result], params: dict[str, LSPAny]
    ) -> Result:
        self.documents.open(document)
        return await self.request(method, params)
