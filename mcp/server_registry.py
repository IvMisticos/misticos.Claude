import asyncio

from language_servers import (
    EXTENSION_TO_SERVER,
    LANGUAGE_SERVERS,
    ensure_installed,
    toolchain_environment,
)
from lsp_client import LanguageServer
from project_files import ProjectFileChanges
from project_roots import git_root, project_root

REPLACED_SERVER_GRACE_SECONDS = 120.0
starting_servers = {}
replaced_servers = set()
project_file_changes = {}


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
    repo = git_root(path)
    key = (name, project_root(name, path, repo))
    changes = file_changes_for(key, repo).since_last_check()
    if changes.config_changed:
        replace_server(key)
    server = await running_server(key)
    server.apply_file_changes(changes.events)
    return server


def file_changes_for(key, repo):
    if key not in project_file_changes:
        name, root = key
        spec = LANGUAGE_SERVERS[name]
        project_file_changes[key] = ProjectFileChanges(
            repo, root, spec["extensions"], spec["config_files"]
        )
    return project_file_changes[key]


def replace_server(key):
    starting = starting_servers.pop(key, None)
    if starting is None:
        return
    replaced_servers.add(starting)
    asyncio.get_running_loop().call_later(
        REPLACED_SERVER_GRACE_SECONDS, stop_replaced_server, starting
    )


def stop_replaced_server(starting):
    replaced_servers.discard(starting)
    starting.add_done_callback(stop_started_server)


async def running_server(key):
    starting = starting_servers.get(key)
    if starting is not None and starting.done() and not started_and_alive(starting):
        stop_started_server(starting)
        starting = None
    if starting is None:
        starting = starting_servers[key] = asyncio.ensure_future(start_server(*key))
    return await asyncio.shield(starting)


def started_ok(starting):
    return starting.done() and not starting.cancelled() and starting.exception() is None


def started_and_alive(starting):
    return started_ok(starting) and starting.result().alive


def stop_started_server(starting):
    if started_ok(starting):
        starting.result().stop()


def stop_all_servers():
    for starting in [*starting_servers.values(), *replaced_servers]:
        stop_started_server(starting)
