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

HOME = Path("/root")
CLAUDE_DIR = HOME / ".claude"
CODEX_DIR = HOME / ".codex"
REPO = Path(__file__).resolve().parent
OLD_REMINDER_COMMAND = "~/.claude/reminder.py"


def run(*command, input_text=None):
    subprocess.run(command, check=True, input=input_text, text=True)


def install_tools():
    run("apt-get", "update")
    run("apt-get", "install", "-y", "git-lfs", "curl", "jq", "gh", "unzip")
    run("bash", "-c", "curl -fsSL https://bun.sh/install | bash -s canary")
    run("bash", "-c", "curl -fsSL https://dot.net/v1/dotnet-install.sh | bash -s -- --channel LTS")
    local_bin = HOME / ".local" / "bin"
    local_bin.mkdir(parents=True, exist_ok=True)
    dotnet_link = local_bin / "dotnet"
    dotnet_link.unlink(missing_ok=True)
    dotnet_link.symlink_to(HOME / ".dotnet" / "dotnet")


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


def remove_if_installed_copy(path):
    if path.exists() and path.read_bytes() == (REPO / "CLAUDE.md").read_bytes():
        path.unlink()


def configure_claude():
    CLAUDE_DIR.mkdir(parents=True, exist_ok=True)
    (CLAUDE_DIR / "reminder.py").unlink(missing_ok=True)
    (CLAUDE_DIR / "output-styles" / "short.md").unlink(missing_ok=True)
    remove_if_installed_copy(CLAUDE_DIR / "CLAUDE.md")
    settings_path = CLAUDE_DIR / "settings.json"
    settings = read_json(settings_path)
    settings["attribution"] = {"commit": "", "pr": "", "sessionUrl": False}
    settings["autoMemoryEnabled"] = False
    settings.pop("outputStyle", None)
    settings["hooks"] = without_old_reminder(settings.get("hooks") or {})
    settings_path.write_text(json.dumps(settings, indent=2) + "\n")
    run("claude", "plugin", "marketplace", "add", "GoogleChrome/modern-web-guidance")
    run("claude", "plugin", "install", "modern-web-guidance@googlechrome", "--scope", "user")
    run("claude", "plugin", "marketplace", "add", str(REPO))
    run("claude", "plugin", "install", "misticos@misticos", "--scope", "user")


def configure_codex():
    if shutil.which("codex") is None:
        return
    CODEX_DIR.mkdir(parents=True, exist_ok=True)
    remove_if_installed_copy(CODEX_DIR / "AGENTS.md")
    config_path = CODEX_DIR / "config.toml"
    config = tomllib.loads(config_path.read_text()) if config_path.exists() else {}
    config.setdefault("personality", "none")
    config.setdefault("memories", {"use_memories": False, "generate_memories": False})
    config_path.write_text(tomli_w.dumps(config))
    run("codex", "plugin", "marketplace", "add", str(REPO))
    run("codex", "plugin", "add", "misticos@misticos")
    print(
        "Codex runs plugin hooks only after you approve them once: "
        "open codex, run /hooks, and trust the misticos hooks."
    )


def main():
    if os.geteuid() != 0:
        sys.exit("run as root: this sets up /root")
    install_tools()
    configure_claude()
    configure_codex()


if __name__ == "__main__":
    main()
