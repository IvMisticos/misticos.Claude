import os
import subprocess

from disks import device_of

COMMAND_TIMEOUT_SECONDS = 120
LIST_NUGET_HTTP_CACHE = ("dotnet", "nuget", "locals", "http-cache", "--list")
CLEAR_NUGET_HTTP_CACHE = ("dotnet", "nuget", "locals", "http-cache", "--clear")
FIND_DOCKER_ROOT = ("docker", "info", "--format", "{{.DockerRootDir}}")
SHOW_DOCKER_CONTEXT = ("docker", "context", "show")
PRUNE_DOCKER_BUILD_CACHE = ("docker", "builder", "prune", "-f")
PRUNE_DANGLING_DOCKER_IMAGES = ("docker", "image", "prune", "-f")


def output_of(command, env=None):
    try:
        result = subprocess.run(
            command,
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=COMMAND_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def ran(command, env=None):
    return output_of(command, env) is not None


def is_on(path, devices):
    return path is not None and device_of(path) in devices


def nuget_http_cache():
    for line in (output_of(LIST_NUGET_HTTP_CACHE) or "").splitlines():
        name, _, path = line.partition(": ")
        if name == "http-cache":
            return path
    return None


def docker_prunes():
    daemon_builder = output_of(SHOW_DOCKER_CONTEXT)
    if daemon_builder:
        builder_env = os.environ | {"BUILDX_BUILDER": daemon_builder}
        yield "the Docker build cache", PRUNE_DOCKER_BUILD_CACHE, builder_env
    yield "dangling Docker images", PRUNE_DANGLING_DOCKER_IMAGES, None


def cleared_caches(devices):
    cleared = []
    if is_on(nuget_http_cache(), devices) and ran(CLEAR_NUGET_HTTP_CACHE):
        cleared.append("the NuGet HTTP cache")
    if is_on(output_of(FIND_DOCKER_ROOT), devices):
        cleared += [cache for cache, prune, env in docker_prunes() if ran(prune, env)]
    return cleared
