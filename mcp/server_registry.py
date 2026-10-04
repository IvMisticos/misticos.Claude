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
        name,
        spec["command"],
        spec["extensions"],
        spec["config_files"],
        root,
        toolchain_environment(),
    )
    await server.start()
    return server


async def server_for(path):
    name = EXTENSION_TO_SERVER.get(path.suffix)
    if name is None:
        raise ValueError(f"no language server for {path.suffix} files")
    key = (name, project_root(name, path))
    server = await running_server(key)
    changes = server.file_changes.since_last_check()
    if changes.config_changed:
        server.stop()
        del starting_servers[key]
        return await running_server(key)
    server.apply_file_changes(changes.events)
    return server


async def running_server(key):
    starting = starting_servers.get(key)
    if starting is not None and starting.done() and not started_and_alive(starting):
        if started_ok(starting):
            starting.result().stop()
        starting = None
    if starting is None:
        starting = starting_servers[key] = asyncio.ensure_future(start_server(*key))
    return await asyncio.shield(starting)


def started_ok(starting):
    return starting.done() and not starting.cancelled() and starting.exception() is None


def started_and_alive(starting):
    return started_ok(starting) and starting.result().alive


def stop_all_servers():
    for starting in starting_servers.values():
        if started_ok(starting):
            starting.result().stop()
