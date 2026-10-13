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
WRITTEN_DENIES_FILE = "misticos-written-denies.json"
WRITTEN_SKILL_OVERRIDES_FILE = "misticos-written-skill-overrides.json"
INSTALLED_PLUGINS = CLAUDE_DIR / "plugins" / "installed_plugins.json"
WEB_GUIDANCE_PLUGIN = "modern-web-guidance@googlechrome"
CLOUD_SESSION_MARK = "CCR_AGENT_PROXY_ENABLED"
AUTO_COMPACT_WINDOW_TOKENS = 400_000
REMOTE_SERVER_NAMES = ("claude-code-remote", "Claude_Code_Remote")
REMOTE_SESSION_TOOLS = (
    "archive_session",
    "unarchive_session",
    "create_session",
    "interrupt_session",
    "list_sessions",
    "set_session_tags",
    "set_session_title",
    "list_environments",
)
USER_INVOCABLE_ONLY = "user-invocable-only"
USER_INVOCABLE_ONLY_SKILLS = (
    "session-start-hook",
    "dataviz",
    "artifact-design",
    "artifact-diagramming",
    "artifact-capabilities",
    "update-config",
    "keybindings-help",
    "code-review",
    "simplify",
    "fewer-permission-prompts",
    "plugin-authoring",
    "init",
    "security-review",
    "loop",
    "run",
    "anthropic-skills:chrome-browser",
    "anthropic-skills:computer-use",
)
DENIED_TOOLS = (
    *(
        f"mcp__{server}__{tool}"
        for server in REMOTE_SERVER_NAMES
        for tool in REMOTE_SESSION_TOOLS
    ),
    "ScheduleWakeup",
    "ShowOnboardingRolePicker",
    "SuggestSkills",
    "DesignSync",
    "SearchPlugins",
    "SuggestPluginInstall",
    "SuggestConnectors",
    "SearchMcpRegistry",
    "mcp__github__create_repository",
    "mcp__github__fork_repository",
    "mcp__github__request_copilot_review",
    "mcp__github__run_secret_scanning",
)

TURN_ENDING_TOOLS = "ReadNotifications,SendMessage"


TOOLCHAIN_BIN_DIRS = (
    HOME / ".local" / "bin",
    HOME / ".bun" / "bin",
    HOME / ".dotnet" / "tools",
)
TOOLCHAIN_PATH = os.pathsep.join(
    [*map(str, TOOLCHAIN_BIN_DIRS), os.environ.get("PATH", "")]
)


def run(*command):
    environment = {
        "DOTNET_ROOT": str(HOME / ".dotnet"),
        **os.environ,
        "PATH": TOOLCHAIN_PATH,
    }
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


class ManagedEntries:
    def __init__(self, file_name, key, wanted):
        self.path = CLAUDE_DIR / file_name
        self.key = key
        self.wanted = wanted
        self.recorded = read_json(self.path).get(key, [])
        self.added = []

    def retired(self, is_retirable=lambda name: True):
        return [
            name
            for name in self.recorded
            if name not in self.wanted and is_retirable(name)
        ]

    def additions(self, kept_names):
        self.added = [name for name in self.wanted if name not in kept_names]
        return self.added

    def record_before_settings_write(self):
        self.write(
            [*self.recorded, *(name for name in self.added if name not in self.recorded)]
        )

    def record_after_settings_write(self):
        self.write(
            [
                name
                for name in self.wanted
                if name in self.recorded or name in self.added
            ]
        )

    def write(self, names):
        if read_json(self.path).get(self.key) == names:
            return
        write_atomically(self.path, json.dumps({self.key: names}, indent=2) + "\n")


def configure_claude_settings():
    CLAUDE_DIR.mkdir(parents=True, exist_ok=True)
    settings_path = CLAUDE_DIR / "settings.json"
    settings = read_json(settings_path)
    wanted = dict(settings)
    wanted["attribution"] = {"commit": "", "pr": "", "sessionUrl": False}
    wanted["autoMemoryEnabled"] = False
    wanted["autoCompactWindow"] = AUTO_COMPACT_WINDOW_TOKENS
    denies = ManagedEntries(WRITTEN_DENIES_FILE, "deny", DENIED_TOOLS)
    permissions = dict(settings.get("permissions", {}))
    retired_denies = denies.retired()
    kept_denies = [
        tool for tool in permissions.get("deny", []) if tool not in retired_denies
    ]
    permissions["deny"] = kept_denies + denies.additions(kept_denies)
    wanted["permissions"] = permissions
    skills = ManagedEntries(
        WRITTEN_SKILL_OVERRIDES_FILE, "skills", USER_INVOCABLE_ONLY_SKILLS
    )
    overrides = settings.get("skillOverrides", {})
    retired_skills = skills.retired(
        lambda skill: overrides.get(skill) == USER_INVOCABLE_ONLY
    )
    kept_overrides = {
        skill: mode for skill, mode in overrides.items() if skill not in retired_skills
    }
    wanted["skillOverrides"] = {
        **kept_overrides,
        **dict.fromkeys(skills.additions(kept_overrides), USER_INVOCABLE_ONLY),
    }
    wanted["env"] = {
        **settings.get("env", {}),
        "CLAUDE_CODE_TERMINAL_MCP_TOOLS": TURN_ENDING_TOOLS,
    }
    denies.record_before_settings_write()
    skills.record_before_settings_write()
    if wanted != settings:
        write_atomically(settings_path, json.dumps(wanted, indent=2) + "\n")
    denies.record_after_settings_write()
    skills.record_after_settings_write()


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
        print(
            f"setup: leaving {config_path} alone, it does not parse: {error}",
            file=sys.stderr,
        )
        return
    wanted = dict(config)
    wanted.setdefault("personality", "none")
    wanted.setdefault("memories", {"use_memories": False, "generate_memories": False})
    if wanted != config:
        write_atomically(config_path, tomli_w.dumps(wanted))


def install_apt_packages():
    packages = ("git-lfs", "curl", "jq", "gh", "unzip")
    if any(shutil.which(package) is None for package in packages):
        run("apt-get", "update")
        run("apt-get", "install", "-y", *packages)


def install_bun():
    if shutil.which("bun") is None and not (HOME / ".bun" / "bin" / "bun").exists():
        run_pipeline("curl -fsSL https://bun.sh/install | bash -s canary")


def install_mise():
    if shutil.which("mise") is None and not (HOME / ".local" / "bin" / "mise").exists():
        run_pipeline("curl -fsSL https://mise.run | sh")


def install_dotnet():
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


def install_cloud_tools():
    if CLOUD_SESSION_MARK not in os.environ or os.geteuid() != 0:
        return
    install_apt_packages()
    install_bun()
    install_mise()
    install_dotnet()


def main():
    install_web_guidance_plugin()
    configure_claude_settings()
    configure_codex()
    install_cloud_tools()


if __name__ == "__main__":
    main()
