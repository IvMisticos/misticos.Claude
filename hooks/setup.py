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
    "modern-web-guidance:chrome-extensions",
    "cowork-plugin-management:cowork-plugin-customizer",
    "cowork-plugin-management:create-cowork-plugin",
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


def write_written_denies(path, tools):
    if read_json(path).get("deny") == tools:
        return
    write_atomically(path, json.dumps({"deny": tools}, indent=2) + "\n")


def write_written_skills(path, skills):
    if read_json(path).get("skills") == skills:
        return
    write_atomically(path, json.dumps({"skills": skills}, indent=2) + "\n")


def configure_claude_settings():
    CLAUDE_DIR.mkdir(parents=True, exist_ok=True)
    settings_path = CLAUDE_DIR / "settings.json"
    settings = read_json(settings_path)
    wanted = dict(settings)
    wanted["attribution"] = {"commit": "", "pr": "", "sessionUrl": False}
    wanted["autoMemoryEnabled"] = False
    wanted["autoCompactWindow"] = AUTO_COMPACT_WINDOW_TOKENS
    permissions = dict(settings.get("permissions", {}))
    written_denies_path = CLAUDE_DIR / WRITTEN_DENIES_FILE
    written_denies = read_json(written_denies_path).get("deny", [])
    retired_denies = [tool for tool in written_denies if tool not in DENIED_TOOLS]
    kept_denies = [
        tool for tool in permissions.get("deny", []) if tool not in retired_denies
    ]
    added_denies = [tool for tool in DENIED_TOOLS if tool not in kept_denies]
    permissions["deny"] = kept_denies + added_denies
    wanted["permissions"] = permissions
    written_skills_path = CLAUDE_DIR / WRITTEN_SKILL_OVERRIDES_FILE
    written_skills = read_json(written_skills_path).get("skills", [])
    retired_skills = [
        skill for skill in written_skills if skill not in USER_INVOCABLE_ONLY_SKILLS
    ]
    kept_overrides = {
        skill: mode
        for skill, mode in settings.get("skillOverrides", {}).items()
        if skill not in retired_skills
    }
    added_skills = [
        skill for skill in USER_INVOCABLE_ONLY_SKILLS if skill not in kept_overrides
    ]
    wanted["skillOverrides"] = {
        **kept_overrides,
        **dict.fromkeys(added_skills, "user-invocable-only"),
    }
    wanted["env"] = {
        **settings.get("env", {}),
        "CLAUDE_CODE_TERMINAL_MCP_TOOLS": TURN_ENDING_TOOLS,
    }
    write_written_denies(
        written_denies_path,
        [*written_denies, *(tool for tool in added_denies if tool not in written_denies)],
    )
    write_written_skills(
        written_skills_path,
        [
            *written_skills,
            *(skill for skill in added_skills if skill not in written_skills),
        ],
    )
    if wanted != settings:
        write_atomically(settings_path, json.dumps(wanted, indent=2) + "\n")
    write_written_denies(
        written_denies_path,
        [tool for tool in DENIED_TOOLS if tool in written_denies or tool in added_denies],
    )
    write_written_skills(
        written_skills_path,
        [
            skill
            for skill in USER_INVOCABLE_ONLY_SKILLS
            if skill in written_skills or skill in added_skills
        ],
    )


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
