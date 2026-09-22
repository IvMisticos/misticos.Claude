#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["tomli-w"]
# ///

import json
import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import tomli_w

HOME = Path.home()
CLAUDE_DIR = HOME / ".claude"
CODEX_DIR = HOME / ".codex"
INSTALLED_PLUGINS = CLAUDE_DIR / "plugins" / "installed_plugins.json"
WEB_GUIDANCE_PLUGIN = "modern-web-guidance@googlechrome"
CLOUD_SESSION_MARK = "CCR_AGENT_PROXY_ENABLED"


TOOLCHAIN_BIN_DIRS = (HOME / ".local" / "bin", HOME / ".bun" / "bin", HOME / ".dotnet" / "tools")
TOOLCHAIN_PATH = os.pathsep.join([*map(str, TOOLCHAIN_BIN_DIRS), os.environ.get("PATH", "")])


def run(*command):
    environment = {"DOTNET_ROOT": str(HOME / ".dotnet"), **os.environ, "PATH": TOOLCHAIN_PATH}
    subprocess.run(command, check=True, stdout=sys.stderr, env=environment)


def run_pipeline(script):
    run("bash", "-o", "pipefail", "-c", script)


def write_atomically(path, text):
    staged = path.with_name(path.name + ".installing")
    staged.write_text(text)
    os.replace(staged, path)


def read_json(path):
    try:
        text = path.read_text()
    except FileNotFoundError:
        return {}
    return json.loads(text) if text.strip() else {}


def configure_claude_settings():
    CLAUDE_DIR.mkdir(parents=True, exist_ok=True)
    settings_path = CLAUDE_DIR / "settings.json"
    settings = read_json(settings_path)
    wanted = dict(settings)
    wanted["attribution"] = {"commit": "", "pr": "", "sessionUrl": False}
    wanted["autoMemoryEnabled"] = False
    if wanted != settings:
        write_atomically(settings_path, json.dumps(wanted, indent=2) + "\n")


def install_web_guidance_plugin():
    installed = read_json(INSTALLED_PLUGINS).get("plugins", {})
    if WEB_GUIDANCE_PLUGIN in installed:
        return
    run("claude", "plugin", "marketplace", "add", "GoogleChrome/modern-web-guidance")
    run("claude", "plugin", "install", WEB_GUIDANCE_PLUGIN, "--scope", "user")


def configure_codex():
    if shutil.which("codex") is None:
        return
    CODEX_DIR.mkdir(parents=True, exist_ok=True)
    config_path = CODEX_DIR / "config.toml"
    try:
        config = tomllib.loads(config_path.read_text()) if config_path.exists() else {}
    except tomllib.TOMLDecodeError as error:
        print(f"setup: leaving {config_path} alone, it does not parse: {error}", file=sys.stderr)
        return
    wanted = dict(config)
    wanted.setdefault("personality", "none")
    wanted.setdefault("memories", {"use_memories": False, "generate_memories": False})
    if wanted != config:
        write_atomically(config_path, tomli_w.dumps(wanted))


def install_language_servers():
    def present(tool):
        return shutil.which(tool, path=TOOLCHAIN_PATH) is not None

    if present("bun") and not present("tsgo"):
        run("bun", "add", "-g", "@typescript/native-preview")
    if present("uv") and not present("ty"):
        run("uv", "tool", "install", "ty")
    if present("dotnet") and not present("csharp-ls"):
        run("dotnet", "tool", "install", "-g", "csharp-ls")


def install_cloud_tools():
    if CLOUD_SESSION_MARK not in os.environ or os.geteuid() != 0:
        return
    packages = ("git-lfs", "curl", "jq", "gh", "unzip")
    if any(shutil.which(package) is None for package in packages):
        run("apt-get", "update")
        run("apt-get", "install", "-y", *packages)
    if shutil.which("bun") is None and not (HOME / ".bun" / "bin" / "bun").exists():
        run_pipeline("curl -fsSL https://bun.sh/install | bash -s canary")
    dotnet = HOME / ".dotnet" / "dotnet"
    if not dotnet.exists():
        run_pipeline("curl -fsSL https://dot.net/v1/dotnet-install.sh | bash -s -- --channel LTS")
    local_bin = HOME / ".local" / "bin"
    local_bin.mkdir(parents=True, exist_ok=True)
    dotnet_link = local_bin / "dotnet"
    dotnet_link.unlink(missing_ok=True)
    dotnet_link.symlink_to(dotnet)


def main():
    install_web_guidance_plugin()
    configure_claude_settings()
    configure_codex()
    install_cloud_tools()
    install_language_servers()


if __name__ == "__main__":
    main()
