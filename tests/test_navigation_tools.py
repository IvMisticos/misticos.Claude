import asyncio
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "mcp"))

from code_navigation import CodeNavigation
from lsp_client import LanguageServer

FAKE_SERVER = Path(__file__).resolve().parent / "fake_language_server.py"
GREETER = "class Greeter:\n    def greet(self) -> None: ...\n"

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
