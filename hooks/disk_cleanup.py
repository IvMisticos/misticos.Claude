import os
import subprocess

COMMAND_TIMEOUT_SECONDS = 120
LIST_NUGET_HTTP_CACHE = ("dotnet", "nuget", "locals", "http-cache", "--list")
CLEAR_NUGET_HTTP_CACHE = ("dotnet", "nuget", "locals", "http-cache", "--clear")
FIND_DOCKER_ROOT = ("docker", "info", "--format", "{{.DockerRootDir}}")
DOCKER_PRUNES = (
    ("the Docker build cache", ("docker", "builder", "prune", "-f")),
    ("dangling Docker images", ("docker", "image", "prune", "-f")),
)


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


def cleared_caches(devices):
    cleared = []
    if is_on(nuget_http_cache(), devices) and ran(CLEAR_NUGET_HTTP_CACHE):
        cleared.append("the NuGet HTTP cache")
    if is_on(docker_root(), devices):
        cleared += [name for name, command in DOCKER_PRUNES if ran(command)]
    return cleared
