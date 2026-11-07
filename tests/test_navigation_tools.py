import asyncio
import sys
from pathlib import Path

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import CallToolResult, TextContent

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "mcp"))

from code_navigation import navigation_server
from lsp_client import LanguageServer

FAKE_SERVER = Path(__file__).resolve().parent / "fake_language_server.py"
GREETER = "class Greeter:\n    def greet(self) -> None: ...\n"
GREET = "def greet() -> None: ...\n"
WELCOME = "def welcome() -> None:\n    greet()\n"


async def agent_reads(
    navigation: MCPServer, tool: str, arguments: dict[str, object]
) -> str:
    try:
        result = await navigation.call_tool(tool, arguments)
    except ToolError as error:
        return str(error)
    assert isinstance(result, CallToolResult)
    [content] = result.content
    assert isinstance(content, TextContent)
    return content.text


async def ask_fake_server(root: Path, tool: str, arguments: dict[str, object]) -> str:
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
        return await agent_reads(navigation_server(fake_server_for), tool, arguments)
    finally:
        server.stop()
        await process.wait()


def agent_reads_from_fake(root: Path, tool: str, **arguments: object) -> str:
    return asyncio.run(ask_fake_server(root, tool, arguments))


def write_greeter(directory: Path) -> Path:
    source = directory / "greeter.py"
    source.write_text(GREETER)
    return source


def test_document_symbols_nest_children_under_their_parent(tmp_path: Path) -> None:
    source = write_greeter(tmp_path)
    symbols = agent_reads_from_fake(tmp_path, "document_symbols", file=str(source))
    assert symbols.splitlines() == [
        f"Greeter (class) {source}:1:7",
        f"  greet (method) {source}:2:9",
    ]


def test_first_workspace_symbols_query_finds_symbols(tmp_path: Path) -> None:
    source = write_greeter(tmp_path)
    symbols = agent_reads_from_fake(
        tmp_path, "workspace_symbols", query="Greeter", file_in_project=str(source)
    )
    assert symbols == f"Greeter (class) {source}:1:7"


def test_workspace_symbols_accept_a_file_that_is_not_utf8(tmp_path: Path) -> None:
    source = tmp_path / "greeter.py"
    source.write_bytes(b"class Greeter:  # caf\xe9\n    def greet(self) -> None: ...\n")
    symbols = agent_reads_from_fake(
        tmp_path, "workspace_symbols", query="Greeter", file_in_project=str(source)
    )
    assert symbols == f"Greeter (class) {source}:1:7"


def test_definition_points_at_the_target_position(tmp_path: Path) -> None:
    source = write_greeter(tmp_path)
    definition = agent_reads_from_fake(
        tmp_path, "definition", file=str(source), line=1, column=7
    )
    assert definition == f"{source}:1:7"


def test_definition_without_a_range_names_the_file(tmp_path: Path) -> None:
    source = write_greeter(tmp_path)
    definition = agent_reads_from_fake(
        tmp_path, "definition", file=str(source), line=2, column=9
    )
    assert definition == str(source)


def test_hover_joins_every_part_of_its_contents(tmp_path: Path) -> None:
    source = write_greeter(tmp_path)
    hover = agent_reads_from_fake(tmp_path, "hover", file=str(source), line=1, column=7)
    assert hover == "class Greeter\nGreets people."


def test_malformed_reply_names_the_server_and_the_method(tmp_path: Path) -> None:
    source = write_greeter(tmp_path)
    definition = agent_reads_from_fake(
        tmp_path, "definition", file=str(source), line=3, column=1
    )
    assert definition.startswith(
        "Error executing tool definition: "
        "fake sent a malformed textDocument/definition reply"
    )


def test_error_reply_reaches_the_agent(tmp_path: Path) -> None:
    source = write_greeter(tmp_path)
    rename = agent_reads_from_fake(
        tmp_path, "rename", file=str(source), line=1, column=7, new_name="Host"
    )
    assert rename == (
        "Error executing tool rename: fake replied with an error: "
        "rename is not supported"
    )


def write_calls(directory: Path) -> tuple[Path, Path]:
    greet = directory / "greet.py"
    greet.write_text(GREET)
    welcome = directory / "welcome.py"
    welcome.write_text(WELCOME)
    return greet, welcome


def test_callers_list_each_caller_with_its_call_sites(tmp_path: Path) -> None:
    greet, welcome = write_calls(tmp_path)
    callers = agent_reads_from_fake(
        tmp_path, "callers", file=str(greet), line=1, column=5
    )
    assert callers.splitlines() == [
        f"welcome (function) {welcome}:1:5",
        f"  called at {welcome}:2:5",
    ]


def test_callees_list_call_sites_in_the_calling_function(tmp_path: Path) -> None:
    greet, welcome = write_calls(tmp_path)
    callees = agent_reads_from_fake(
        tmp_path, "callees", file=str(welcome), line=1, column=5
    )
    assert callees.splitlines() == [
        f"greet (function) {greet}:1:5",
        f"  called at {welcome}:2:5",
    ]
