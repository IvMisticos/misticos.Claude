import asyncio
import os
import shutil
import sys
from pathlib import Path

LANGUAGE_SERVERS = {
    "typescript": {
        "command": ["tsgo", "--lsp", "-stdio"],
        "install": ["bun", "add", "-g", "@typescript/native-preview"],
        "extensions": {
            ".ts": "typescript",
            ".tsx": "typescriptreact",
            ".mts": "typescript",
            ".cts": "typescript",
            ".js": "javascript",
            ".jsx": "javascriptreact",
            ".mjs": "javascript",
            ".cjs": "javascript",
        },
    },
    "csharp": {
        "command": ["csharp-ls"],
        "install": ["dotnet", "tool", "install", "-g", "csharp-ls"],
        "extensions": {".cs": "csharp"},
    },
    "python": {
        "command": ["ty", "server"],
        "install": ["uv", "tool", "install", "ty"],
        "extensions": {".py": "python", ".pyi": "python"},
    },
}
EXTENSION_TO_SERVER = {
    extension: name
    for name, server in LANGUAGE_SERVERS.items()
    for extension in server["extensions"]
}
TOOLCHAIN_BIN_DIRS = (".local/bin", ".bun/bin", ".dotnet/tools", ".dotnet")


def toolchain_environment():
    home = Path.home()
    environment = dict(os.environ)
    bin_dirs = [str(home / directory) for directory in TOOLCHAIN_BIN_DIRS]
    environment["PATH"] = os.pathsep.join([*bin_dirs, environment.get("PATH", "")])
    environment.setdefault("DOTNET_ROOT", str(home / ".dotnet"))
    return environment


INSTALL_TIMEOUT_SECONDS = 600.0
installs = {}


def installed_binary(spec, environment):
    return shutil.which(spec["command"][0], path=environment["PATH"])


async def ensure_installed(name):
    spec = LANGUAGE_SERVERS[name]
    environment = toolchain_environment()
    if installed_binary(spec, environment):
        return
    install = installs.get(name)
    if install is None or install.done():
        install = installs[name] = asyncio.ensure_future(
            install_server(spec, environment)
        )
    await asyncio.wait_for(asyncio.shield(install), INSTALL_TIMEOUT_SECONDS)


async def install_server(spec, environment):
    binary, installer = spec["command"][0], spec["install"][0]
    if not shutil.which(installer, path=environment["PATH"]):
        raise RuntimeError(
            f"{binary} is missing and {installer} is not installed to fetch it"
        )
    print(f"installing {binary} with {' '.join(spec['install'])}", file=sys.stderr)
    process = await asyncio.create_subprocess_exec(
        *spec["install"],
        env=environment,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=sys.stderr,
        stderr=sys.stderr,
    )
    await process.wait()
    if process.returncode != 0:
        raise RuntimeError(
            f"{' '.join(spec['install'])} exited with {process.returncode}"
        )
    if not installed_binary(spec, environment):
        raise RuntimeError(
            f"{' '.join(spec['install'])} finished but {binary} is still not on PATH"
        )
