import contextlib
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

COMMAND_TIMEOUT_SECONDS = 120
LIST_NUGET_HTTP_CACHE = ("dotnet", "nuget", "locals", "http-cache", "--list")
CLEAR_NUGET_HTTP_CACHE = ("dotnet", "nuget", "locals", "http-cache", "--clear")
FIND_DOCKER_ROOT = ("docker", "info", "--format", "{{.DockerRootDir}}")
DOCKER_PRUNES = (
    ("the Docker build cache", ("docker", "builder", "prune", "-f")),
    ("dangling Docker images", ("docker", "image", "prune", "-f")),
)
DOTNET_PROJECT_SUFFIXES = {".csproj", ".fsproj", ".vbproj"}
RECENTLY_WRITTEN_SECONDS = 15 * 60


def output_of(command):
    try:
        result = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=COMMAND_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def ran(command):
    return output_of(command) is not None


def device_of(path):
    try:
        return str(os.stat(path).st_dev)
    except OSError:
        return None


def is_on(path, devices):
    return path is not None and device_of(path) in devices


def nuget_http_cache():
    for line in (output_of(LIST_NUGET_HTTP_CACHE) or "").splitlines():
        name, _, path = line.partition(": ")
        if name == "http-cache":
            return path
    return None


def docker_root():
    return output_of(FIND_DOCKER_ROOT) or None


def bun_links_projects_to_its_cache():
    return sys.platform != "darwin"


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


def was_written_recently(path):
    try:
        return time.time() - path.lstat().st_mtime < RECENTLY_WRITTEN_SECONDS
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


def cleared_bun_cache(cache):
    if not cache.is_dir():
        return False
    unused = [
        entry
        for entry in cache.iterdir()
        if not was_written_recently(entry) and is_unused(entry)
    ]
    for entry in unused:
        delete(entry)
    return bool(unused)


def cleared_caches(devices):
    cleared = []
    if is_on(nuget_http_cache(), devices) and ran(CLEAR_NUGET_HTTP_CACHE):
        cleared.append("the NuGet HTTP cache")
    if is_on(docker_root(), devices):
        cleared += [name for name, command in DOCKER_PRUNES if ran(command)]
    bun_cache = bun_install_cache()
    if (
        bun_links_projects_to_its_cache()
        and is_on(bun_cache, devices)
        and cleared_bun_cache(bun_cache)
    ):
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
