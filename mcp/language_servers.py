import asyncio
import os
import shutil
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


async def ensure_installed(name):
    spec = LANGUAGE_SERVERS[name]
    environment = toolchain_environment()
    binary, installer = spec["command"][0], spec["install"][0]
    if shutil.which(binary, path=environment["PATH"]):
        return
    if not shutil.which(installer, path=environment["PATH"]):
        raise RuntimeError(
            f"{binary} is missing and {installer} is not installed to fetch it"
        )
    process = await asyncio.create_subprocess_exec(
        *spec["install"],
        env=environment,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await process.communicate()
    if process.returncode != 0:
        raise RuntimeError(
            f"installing {binary} failed: {stderr.decode(errors='replace').strip()[-500:]}"
        )
