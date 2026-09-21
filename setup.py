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
OLD_REMINDER_COMMAND = "~/.claude/reminder.py"
CLOUD_SESSION_MARK = "CCR_AGENT_PROXY_ENABLED"


def run(*command):
    subprocess.run(command, check=True, stdout=sys.stderr)


def read_json(path):
    try:
        text = path.read_text()
    except FileNotFoundError:
        return {}
    return json.loads(text) if text.strip() else {}


def without_old_reminder(hooks):
    kept = {}
    for event, groups in hooks.items():
        kept_groups = []
        for group in groups:
            entries = [
                entry
                for entry in group.get("hooks", [])
                if not str(entry.get("command", "")).startswith(OLD_REMINDER_COMMAND)
            ]
            if entries:
                kept_groups.append({**group, "hooks": entries})
        if kept_groups:
            kept[event] = kept_groups
    return kept


def configure_claude_settings():
    CLAUDE_DIR.mkdir(parents=True, exist_ok=True)
    settings_path = CLAUDE_DIR / "settings.json"
    settings = read_json(settings_path)
    wanted = dict(settings)
    wanted["attribution"] = {"commit": "", "pr": "", "sessionUrl": False}
    wanted["autoMemoryEnabled"] = False
    wanted.pop("outputStyle", None)
    wanted["hooks"] = without_old_reminder(settings.get("hooks") or {})
    if wanted != settings:
        settings_path.write_text(json.dumps(wanted, indent=2) + "\n")


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
    config = tomllib.loads(config_path.read_text()) if config_path.exists() else {}
    wanted = dict(config)
    wanted.setdefault("personality", "none")
    wanted.setdefault("memories", {"use_memories": False, "generate_memories": False})
    if wanted != config:
        config_path.write_text(tomli_w.dumps(wanted))


def install_cloud_tools():
    if CLOUD_SESSION_MARK not in os.environ or os.geteuid() != 0:
        return
    if shutil.which("git-lfs") is None:
        run("apt-get", "update")
        run("apt-get", "install", "-y", "git-lfs", "curl", "jq", "gh", "unzip")
    if shutil.which("bun") is None and not (HOME / ".bun" / "bin" / "bun").exists():
        run("bash", "-c", "curl -fsSL https://bun.sh/install | bash -s canary")
    local_bin = HOME / ".local" / "bin"
    dotnet_link = local_bin / "dotnet"
    if not dotnet_link.exists():
        run("bash", "-c", "curl -fsSL https://dot.net/v1/dotnet-install.sh | bash -s -- --channel LTS")
        local_bin.mkdir(parents=True, exist_ok=True)
        dotnet_link.symlink_to(HOME / ".dotnet" / "dotnet")


def main():
    configure_claude_settings()
    install_web_guidance_plugin()
    configure_codex()
    install_cloud_tools()


if __name__ == "__main__":
    main()
