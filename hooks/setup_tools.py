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
from pathlib import Path

from json_values import JsonObject, JsonValue, dict_or_empty, json_object

HOOKS_DIR = Path(__file__).resolve().parent
HOME = Path.home()
CLAUDE_SETTINGS = HOME / ".claude" / "settings.json"
INSTALLED_PLUGINS = HOME / ".claude" / "plugins" / "installed_plugins.json"
WEB_GUIDANCE_NAME = "modern-web-guidance"
WEB_GUIDANCE_PLUGIN = f"{WEB_GUIDANCE_NAME}@googlechrome"
WEB_GUIDANCE_MARKETPLACE = "GoogleChrome/modern-web-guidance"
CLOUD_SESSION_MARK = "CCR_AGENT_PROXY_ENABLED"
MISE = HOME / ".local" / "bin" / "mise"
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

TOOLCHAIN_BIN_DIRS = (
    HOME / ".local" / "bin",
    HOME / ".bun" / "bin",
    HOME / ".dotnet" / "tools",
)
TOOLCHAIN_PATH = os.pathsep.join(
    [*map(str, TOOLCHAIN_BIN_DIRS), os.environ.get("PATH", "")]
)


def run(*command: str, cwd: Path | None = None) -> None:
    environment = {
        "DOTNET_ROOT": str(HOME / ".dotnet"),
        "MISE_YES": "1",
        **os.environ,
        "PATH": TOOLCHAIN_PATH,
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
    packages = ("git-lfs", "curl", "jq", "gh", "unzip", "valgrind")
    if any(shutil.which(package) is None for package in packages):
        run("apt-get", "update")
        run("apt-get", "install", "-y", *packages)


def install_bun() -> None:
    if shutil.which("bun") is None and not (HOME / ".bun" / "bin" / "bun").exists():
        run_pipeline("curl -fsSL https://bun.sh/install | bash -s canary")


def install_mise() -> None:
    if shutil.which("mise") is None and not MISE.exists():
        run_pipeline("curl -fsSL https://mise.run | sh")


def project_dir() -> Path:
    return Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())


def has_mise_config(directory: Path) -> bool:
    return any(
        next(directory.glob(pattern), None) is not None
        for pattern in MISE_CONFIG_PATTERNS
    )


def directories_with_mise_config() -> list[Path]:
    root = project_dir()
    candidates = [root, *sorted(child for child in root.iterdir() if child.is_dir())]
    return [directory for directory in candidates if has_mise_config(directory)]


def install_mise_tools(directory: Path) -> None:
    mise = shutil.which("mise", path=TOOLCHAIN_PATH) or str(MISE)
    run(mise, "trust", "--all", "--quiet", cwd=directory)
    try:
        run(mise, "install", cwd=directory)
    except subprocess.CalledProcessError:
        run(mise, "install", cwd=directory)


def install_mise_tools_of_projects() -> None:
    failed = []
    for directory in directories_with_mise_config():
        try:
            install_mise_tools(directory)
        except subprocess.CalledProcessError:
            failed.append(str(directory))
    if failed:
        sys.exit(f"mise install failed in {', '.join(failed)}")


def install_dotnet() -> None:
    dotnet = HOME / ".dotnet" / "dotnet"
    if not dotnet.exists():
        run_pipeline(
            "curl -fsSL https://dot.net/v1/dotnet-install.sh | bash -s -- --channel LTS"
        )
    local_bin = HOME / ".local" / "bin"
    local_bin.mkdir(parents=True, exist_ok=True)
    dotnet_link = local_bin / "dotnet"
    dotnet_link.unlink(missing_ok=True)
    dotnet_link.symlink_to(dotnet)


def install_cloud_tools() -> None:
    if CLOUD_SESSION_MARK not in os.environ or os.geteuid() != 0:
        return
    install_apt_packages()
    install_bun()
    install_mise()
    install_dotnet()
    install_mise_tools_of_projects()


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
