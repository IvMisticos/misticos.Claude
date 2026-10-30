import asyncio
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import TypedDict

SOLUTION_SUFFIXES = (".sln", ".slnx", ".slnf")
PROJECT_SUFFIXES = (".csproj",)


class LanguageServerSpec(TypedDict):
    command: list[str]
    install: list[str]
    extensions: dict[str, str]
    config_files: list[str]


LANGUAGE_SERVERS: dict[str, LanguageServerSpec] = {
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
        "config_files": ["tsconfig*.json", "jsconfig*.json", "package.json"],
    },
    "csharp": {
        "command": ["csharp-ls"],
        "install": ["dotnet", "tool", "install", "-g", "csharp-ls"],
        "extensions": {".cs": "csharp"},
        "config_files": [
            *(f"*{suffix}" for suffix in (*PROJECT_SUFFIXES, *SOLUTION_SUFFIXES)),
            "*.props",
            "*.targets",
            "global.json",
        ],
    },
    "python": {
        "command": ["ty", "server"],
        "install": ["uv", "tool", "install", "ty"],
        "extensions": {".py": "python", ".pyi": "python"},
        "config_files": ["pyproject.toml", "ty.toml"],
    },
}
EXTENSION_TO_SERVER = {
    extension: name
    for name, server in LANGUAGE_SERVERS.items()
    for extension in server["extensions"]
}
TOOLCHAIN_BIN_DIRS = (".local/bin", ".bun/bin", ".dotnet/tools", ".dotnet")


def dotnet_root_from_mise(path: str) -> Path | None:
    mise = shutil.which("mise", path=path)
    if mise is None:
        return None
    found = subprocess.run(
        [mise, "where", "dotnet"],
        capture_output=True,
        text=True,
        check=False,
        cwd=Path.home(),
    )
    return Path(found.stdout.strip()).resolve() if found.returncode == 0 else None


def dotnet_root(path: str) -> Path | None:
    dotnet = shutil.which("dotnet", path=path)
    resolved = Path(dotnet).resolve() if dotnet else None
    if resolved is not None and resolved.name == "dotnet":
        return resolved.parent
    return dotnet_root_from_mise(path)


def toolchain_environment() -> dict[str, str]:
    home = Path.home()
    environment = dict(os.environ)
    bin_dirs = [str(home / directory) for directory in TOOLCHAIN_BIN_DIRS]
    environment["PATH"] = os.pathsep.join([*bin_dirs, environment.get("PATH", "")])
    root = dotnet_root(environment["PATH"])
    if root is not None:
        environment.setdefault("DOTNET_ROOT", str(root))
    return environment


INSTALL_TIMEOUT_SECONDS = 600.0
installs: dict[str, asyncio.Future[None]] = {}


def installed_binary(
    spec: LanguageServerSpec, environment: dict[str, str]
) -> str | None:
    return shutil.which(spec["command"][0], path=environment["PATH"])


async def ensure_installed(name: str) -> None:
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


def install_command(spec: LanguageServerSpec, environment: dict[str, str]) -> list[str]:
    binary, installer = spec["command"][0], spec["install"][0]
    if shutil.which(installer, path=environment["PATH"]):
        return spec["install"]
    mise = shutil.which("mise", path=environment["PATH"])
    if mise is None:
        raise RuntimeError(
            f"{binary} is missing and {installer} is not installed to fetch it"
        )
    return [mise, "--quiet", "x", installer, "--", *spec["install"]]


async def install_server(spec: LanguageServerSpec, environment: dict[str, str]) -> None:
    binary = spec["command"][0]
    command = install_command(spec, environment)
    print(f"installing {binary} with {' '.join(spec['install'])}", file=sys.stderr)
    process = await asyncio.create_subprocess_exec(
        *command,
        env=environment,
        cwd=Path.home(),
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
