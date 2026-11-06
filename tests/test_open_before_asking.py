import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "mcp"))

from lsp_client import LanguageServer
from lsp_types import LSPAny
from text_positions import to_uri

RECORDING_SERVER = Path(__file__).resolve().parent / "recording_language_server.py"


async def notifications_before_asking(source: Path) -> list[LSPAny]:
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        RECORDING_SERVER,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
    )
    server = LanguageServer("recording", process, {".ts": "typescript"}, source.parent)
    try:
        return await server.ask_about(source, "workspace/symbol", {"query": ""})
    finally:
        server.stop()
        await process.wait()


def test_asking_about_a_file_opens_it_first(tmp_path: Path) -> None:
    source = tmp_path / "main.ts"
    source.write_text("export const answer = 42;\n")
    notifications = asyncio.run(notifications_before_asking(source))
    assert [
        (notification["method"], notification["params"]["textDocument"]["uri"])
        for notification in notifications
    ] == [("textDocument/didOpen", to_uri(source))]
