#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# [tool.ty.environment]
# root = ["."]
# ///

import os
import shutil
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import NamedTuple

from install_lock import install_lock
from json_values import JsonObject, JsonValue, dict_or_empty, json_object

HOOKS_DIR = Path(__file__).resolve().parent
HOME = Path.home()
CLAUDE_SETTINGS = HOME / ".claude" / "settings.json"
INSTALLED_PLUGINS = HOME / ".claude" / "plugins" / "installed_plugins.json"
WEB_GUIDANCE_NAME = "modern-web-guidance"
WEB_GUIDANCE_PLUGIN = f"{WEB_GUIDANCE_NAME}@googlechrome"
WEB_GUIDANCE_MARKETPLACE = "GoogleChrome/modern-web-guidance"
CLOUD_SESSION_MARK = "CCR_AGENT_PROXY_ENABLED"
LOCAL_BIN = HOME / ".local" / "bin"
MISE = LOCAL_BIN / "mise"


class PluginTool(NamedTuple):
    version: str
    binaries: tuple[str, ...]
    lazy_unless_project_has: tuple[str, ...] = ()


PLUGIN_TOOLS = {
    "uv": PluginTool("latest", ("uv", "uvx")),
    "gh": PluginTool("latest", ("gh",)),
    "jq": PluginTool("latest", ("jq",)),
    "git-lfs": PluginTool("latest", ("git-lfs",)),
    "bun": PluginTool(
        "latest",
        ("bun", "bunx"),
        ("bun.lock", "bun.lockb", "bunfig.toml", "package.json"),
    ),
    "dotnet": PluginTool(
        "lts",
        ("dotnet",),
        (
            "*.sln",
            "*.slnx",
            "*.slnf",
            "*.csproj",
            "*.fsproj",
            "*.vbproj",
            "global.json",
        ),
    ),
}
MISE_CONFIG_PATTERNS = (
    "mise.toml",
    "mise.*.toml",
    ".mise.toml",
    ".mise.*.toml",
    "mise/config.toml",
    "mise/config.*.toml",
    ".mise/config.toml",
    ".mise/config.*.toml",
    ".config/mise.toml",
    ".config/mise/config.toml",
    ".config/mise/config.*.toml",
    ".config/mise/conf.d/*.toml",
    ".tool-versions",
)


def mise_global_config() -> Path:
    if config_file := os.environ.get("MISE_GLOBAL_CONFIG_FILE"):
        return Path(config_file)
    config_home = Path(os.environ.get("XDG_CONFIG_HOME") or HOME / ".config")
    config_dir = os.environ.get("MISE_CONFIG_DIR") or config_home / "mise"
    return Path(config_dir) / "config.toml"


MISE_GLOBAL_CONFIG = mise_global_config()
TOOLCHAIN_BIN_DIRS = (
    LOCAL_BIN,
    HOME / ".bun" / "bin",
    HOME / ".dotnet" / "tools",
)
TOOLCHAIN_PATH = os.pathsep.join(
    [*map(str, TOOLCHAIN_BIN_DIRS), os.environ.get("PATH", "")]
)


def run(
    *command: str, cwd: Path | None = None, overrides: Mapping[str, str] | None = None
) -> None:
    environment = {
        "MISE_YES": "1",
        **os.environ,
        "PATH": TOOLCHAIN_PATH,
        **(overrides or {}),
    }
    subprocess.run(command, check=True, stdout=sys.stderr, env=environment, cwd=cwd)


def run_pipeline(script: str) -> None:
    run("bash", "-o", "pipefail", "-c", script)


def read_json_leniently(path: Path) -> JsonObject:
    try:
        return json_object(path.read_text()) or {}
    except OSError:
        return {}


def web_guidance_plugin_choice() -> JsonValue:
    settings = read_json_leniently(CLAUDE_SETTINGS)
    enabled = dict_or_empty(settings.get("enabledPlugins"))
    return enabled.get(WEB_GUIDANCE_PLUGIN)


def web_guidance_plugin_wanted() -> bool:
    plugins = read_json_leniently(INSTALLED_PLUGINS).get("plugins")
    installed = dict_or_empty(plugins)
    return (
        WEB_GUIDANCE_PLUGIN not in installed
        and web_guidance_plugin_choice() is not False
    )


def install_web_guidance_plugin() -> None:
    run(
        "claude",
        "plugin",
        "install",
        WEB_GUIDANCE_NAME,
        "--marketplace",
        WEB_GUIDANCE_MARKETPLACE,
        "--scope",
        "user",
    )


def enable_web_guidance_plugin() -> None:
    run("claude", "plugin", "enable", WEB_GUIDANCE_PLUGIN, "--scope", "user")


def install_apt_packages() -> None:
    packages = ("curl", "unzip", "valgrind")
    if any(shutil.which(package) is None for package in packages):
        run("apt-get", "update")
        run("apt-get", "install", "-y", *packages)


def install_mise() -> None:
    if shutil.which("mise") is None and not MISE.exists():
        run_pipeline("curl -fsSL https://mise.run | sh")


def mise() -> str:
    return shutil.which("mise", path=TOOLCHAIN_PATH) or str(MISE)


def has_global_mise_tool(name: str) -> bool:
    lookup = subprocess.run(
        (mise(), "config", "get", "--global", f"tools.{name}"),
        capture_output=True,
        check=False,
        cwd=HOME,
    )
    return lookup.returncode == 0


def register_global_mise_tool(name: str, version: str) -> None:
    if not has_global_mise_tool(name):
        run(mise(), "config", "set", "--global", f"tools.{name}", version, cwd=HOME)


def create_global_mise_config() -> None:
    MISE_GLOBAL_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    MISE_GLOBAL_CONFIG.touch()


def register_plugin_tools() -> None:
    create_global_mise_config()
    for name, tool in PLUGIN_TOOLS.items():
        register_global_mise_tool(name, tool.version)


def project_uses(tool: PluginTool) -> bool:
    return any(
        has_any_file(directory, tool.lazy_unless_project_has)
        for directory in project_directories()
    )


def plugin_tools_wanted_now() -> list[str]:
    return [
        name
        for name, tool in PLUGIN_TOOLS.items()
        if not tool.lazy_unless_project_has or project_uses(tool)
    ]


def run_with_one_retry(
    *command: str, cwd: Path, overrides: Mapping[str, str] | None = None
) -> None:
    try:
        run(*command, cwd=cwd, overrides=overrides)
    except subprocess.CalledProcessError:
        run(*command, cwd=cwd, overrides=overrides)


def install_plugin_tools() -> list[str]:
    failed = []
    for name in plugin_tools_wanted_now():
        try:
            run_with_one_retry(mise(), "install", name, cwd=HOME)
        except subprocess.CalledProcessError:
            failed.append(f"mise install {name}")
    return failed


def installed_mise_binary(name: str) -> Path | None:
    found = subprocess.run(
        (mise(), "which", name), capture_output=True, text=True, check=False, cwd=HOME
    )
    return Path(found.stdout.strip()) if found.returncode == 0 else None


def link_into_local_bin(name: str, binary: Path) -> None:
    link = LOCAL_BIN / name
    if link.exists() and not link.is_symlink():
        return
    link.unlink(missing_ok=True)
    link.symlink_to(binary)


def link_installed_plugin_binaries() -> None:
    LOCAL_BIN.mkdir(parents=True, exist_ok=True)
    for tool in PLUGIN_TOOLS.values():
        for name in tool.binaries:
            if binary := installed_mise_binary(name):
                link_into_local_bin(name, binary)


def set_up_git_lfs() -> list[str]:
    try:
        run("git", "lfs", "install", "--skip-repo", cwd=HOME)
    except subprocess.CalledProcessError:
        return ["git lfs install"]
    return []


def project_dir() -> Path:
    return Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())


def has_any_file(directory: Path, patterns: tuple[str, ...]) -> bool:
    return any(next(directory.glob(pattern), None) is not None for pattern in patterns)


def project_directories() -> list[Path]:
    root = project_dir()
    return [root, *sorted(child for child in root.iterdir() if child.is_dir())]


def directories_with_mise_config() -> list[Path]:
    return [
        directory
        for directory in project_directories()
        if has_any_file(directory, MISE_CONFIG_PATTERNS)
    ]


def ignoring_global_mise_config() -> dict[str, str]:
    ignored = [os.environ.get("MISE_IGNORED_CONFIG_PATHS"), str(MISE_GLOBAL_CONFIG)]
    return {"MISE_IGNORED_CONFIG_PATHS": os.pathsep.join(filter(None, ignored))}


def install_mise_tools(directory: Path) -> None:
    run(mise(), "trust", "--all", "--quiet", cwd=directory)
    run_with_one_retry(
        mise(), "install", cwd=directory, overrides=ignoring_global_mise_config()
    )


def install_mise_tools_of_projects() -> list[str]:
    failed = []
    for directory in directories_with_mise_config():
        try:
            install_mise_tools(directory)
        except subprocess.CalledProcessError:
            failed.append(f"mise install in {directory}")
    return failed


def install_cloud_tools() -> None:
    if CLOUD_SESSION_MARK not in os.environ or os.geteuid() != 0:
        return
    install_apt_packages()
    with install_lock():
        install_mise()
        register_plugin_tools()
        failed = install_plugin_tools()
        link_installed_plugin_binaries()
    failed += set_up_git_lfs()
    failed += install_mise_tools_of_projects()
    if failed:
        sys.exit(f"tool setup failed: {', '.join(failed)}")


def reapply_settings() -> None:
    run(str(HOOKS_DIR / "run.sh"), "setup_settings.py")


def set_up_web_guidance_plugin() -> None:
    try:
        install_web_guidance_plugin()
    finally:
        reapply_settings()
    if web_guidance_plugin_choice() is not True:
        enable_web_guidance_plugin()


def main() -> None:
    try:
        if web_guidance_plugin_wanted():
            set_up_web_guidance_plugin()
    finally:
        install_cloud_tools()


if __name__ == "__main__":
    main()
