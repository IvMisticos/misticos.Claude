import os
from pathlib import Path

LANGUAGE_SERVERS = {
    "typescript": {
        "command": ["tsgo", "--lsp", "-stdio"],
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
    "csharp": {"command": ["csharp-ls"], "extensions": {".cs": "csharp"}},
    "python": {
        "command": ["ty", "server"],
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
