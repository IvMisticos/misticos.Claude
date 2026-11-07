import asyncio
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "mcp"))

from code_navigation import CodeNavigation
from lsp_client import LanguageServer

FAKE_SERVER = Path(__file__).resolve().parent / "fake_language_server.py"
GREETER = "class Greeter:\n    def greet(self) -> None: ...\n"
CALLS = "def greet() -> None: ...\ndef welcome() -> None:\n    greet()\n"

type Ask = Callable[[CodeNavigation], Awaitable[str]]


async def ask_fake_server(root: Path, ask: Ask) -> str:
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        FAKE_SERVER,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
    )
    server = LanguageServer("fake", process, {".py": "python"}, root)

    async def fake_server_for(path: Path) -> LanguageServer:
        return server

    try:
        await server.initialize()
        return await ask(CodeNavigation(fake_server_for))
    finally:
        server.stop()
        await process.wait()


def test_document_symbols_nest_children_under_their_parent(tmp_path: Path) -> None:
    source = tmp_path / "greeter.py"
    source.write_text(GREETER)
    symbols = asyncio.run(
        ask_fake_server(tmp_path, lambda tools: tools.document_symbols(str(source)))
    )
    assert symbols.splitlines() == [
        f"Greeter (class) {source}:1:7",
        f"  greet (method) {source}:2:9",
    ]


def test_first_workspace_symbols_query_finds_symbols(tmp_path: Path) -> None:
    source = tmp_path / "greeter.py"
    source.write_text(GREETER)
    symbols = asyncio.run(
        ask_fake_server(
            tmp_path, lambda tools: tools.workspace_symbols("Greeter", str(source))
        )
    )
    assert symbols == f"Greeter (class) {source}:1:7"


def test_workspace_symbols_accept_a_file_that_is_not_utf8(tmp_path: Path) -> None:
    source = tmp_path / "greeter.py"
    source.write_bytes(b"class Greeter:  # caf\xe9\n    def greet(self) -> None: ...\n")
    symbols = asyncio.run(
        ask_fake_server(
            tmp_path, lambda tools: tools.workspace_symbols("Greeter", str(source))
        )
    )
    assert symbols == f"Greeter (class) {source}:1:7"


def test_callers_list_each_caller_with_its_call_sites(tmp_path: Path) -> None:
    source = tmp_path / "calls.py"
    source.write_text(CALLS)
    callers = asyncio.run(
        ask_fake_server(tmp_path, lambda tools: tools.callers(str(source), 1, 5))
    )
    assert callers.splitlines() == [
        f"welcome (function) {source}:2:5",
        f"  called at {source}:3:5",
    ]


def test_callees_list_call_sites_in_the_calling_function(tmp_path: Path) -> None:
    source = tmp_path / "calls.py"
    source.write_text(CALLS)
    callees = asyncio.run(
        ask_fake_server(tmp_path, lambda tools: tools.callees(str(source), 2, 5))
    )
    assert callees.splitlines() == [
        f"greet (function) {source}:1:5",
        f"  called at {source}:3:5",
    ]


def test_malformed_reply_raises_a_validation_error(tmp_path: Path) -> None:
    source = tmp_path / "greeter.py"
    source.write_text(GREETER)
    with pytest.raises(ValidationError):
        asyncio.run(
            ask_fake_server(tmp_path, lambda tools: tools.definition(str(source), 1, 7))
        )
