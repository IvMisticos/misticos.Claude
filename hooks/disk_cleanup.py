import contextlib
import os
import shutil
import subprocess
from pathlib import Path
from typing import NamedTuple

COMMAND_TIMEOUT_SECONDS = 120
CACHE_COMMANDS = (
    ("the NuGet HTTP cache", ("dotnet", "nuget", "locals", "http-cache", "--clear")),
    ("the Docker build cache", ("docker", "builder", "prune", "-f")),
    ("dangling Docker images", ("docker", "image", "prune", "-f")),
)
DOTNET_PROJECT_SUFFIXES = {".csproj", ".fsproj", ".vbproj"}


class Cleanup(NamedTuple):
    cleared_caches: list[str]
    build_output: list[Path]


def ran(command):
    try:
        result = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=COMMAND_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def bun_install_cache():
    if cache := os.environ.get("BUN_INSTALL_CACHE_DIR"):
        return Path(cache)
    bun_home = os.environ.get("BUN_INSTALL") or Path.home() / ".bun"
    return Path(bun_home) / "install" / "cache"


def files_under(path):
    if path.is_symlink() or not path.is_dir():
        yield path
        return
    for parent, _, files in os.walk(path):
        yield from (Path(parent) / name for name in files)


def is_linked_from_a_project(file):
    try:
        return file.lstat().st_nlink > 1
    except OSError:
        return True


def is_unused(cache_entry):
    return not any(map(is_linked_from_a_project, files_under(cache_entry)))


def delete(path):
    if path.is_symlink() or not path.is_dir():
        with contextlib.suppress(OSError):
            path.unlink()
    else:
        shutil.rmtree(path, ignore_errors=True)


def cleared_bun_cache():
    cache = bun_install_cache()
    if not cache.is_dir():
        return False
    unused = [entry for entry in cache.iterdir() if is_unused(entry)]
    for entry in unused:
        delete(entry)
    return bool(unused)


def cleared_caches():
    cleared = [name for name, command in CACHE_COMMANDS if ran(command)]
    if cleared_bun_cache():
        cleared.append("unused packages in the bun install cache")
    return cleared


def is_build_output(folder, sibling_files):
    match folder:
        case "node_modules" | ".venv":
            return True
        case "bin" | "obj":
            suffixes = {Path(name).suffix for name in sibling_files}
            return bool(suffixes & DOTNET_PROJECT_SUFFIXES)
        case "target":
            return "Cargo.toml" in sibling_files
    return False


def build_output_folders(root):
    for parent, folders, files in os.walk(root):
        found = [folder for folder in folders if is_build_output(folder, files)]
        folders[:] = [folder for folder in folders if folder not in (*found, ".git")]
        yield from (Path(parent) / folder for folder in found)


def deleted_build_output(root):
    folders = list(build_output_folders(root))
    for folder in folders:
        shutil.rmtree(folder, ignore_errors=True)
    return folders


def clean_up(scratchpad):
    build_output = deleted_build_output(scratchpad) if scratchpad else []
    return Cleanup(cleared_caches(), build_output)
