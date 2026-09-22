import asyncio

from language_servers import (
    LANGUAGE_SERVERS,
    EXTENSION_TO_SERVER,
    ensure_installed,
    toolchain_environment,
)
from lsp_client import LanguageServer
from project_roots import project_root

starting_servers = {}


async def start_server(name, root):
    await ensure_installed(name)
    spec = LANGUAGE_SERVERS[name]
    server = LanguageServer(
        name, spec["command"], spec["extensions"], root, toolchain_environment()
    )
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
