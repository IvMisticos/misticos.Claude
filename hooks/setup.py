#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = ["tomli-w"]
# [tool.ty.environment]
# root = ["."]
# python = "../.venv"
# ///

import json
import os
import shutil
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

import tomli_w
from json_values import JsonObject, JsonValue, dict_or_empty

HOME = Path.home()
CLAUDE_DIR = HOME / ".claude"
CODEX_DIR = HOME / ".codex"
INSTALLED_PLUGINS = CLAUDE_DIR / "plugins" / "installed_plugins.json"
WEB_GUIDANCE_PLUGIN = "modern-web-guidance@googlechrome"
CLOUD_SESSION_MARK = "CCR_AGENT_PROXY_ENABLED"
AUTO_COMPACT_WINDOW_TOKENS = 400_000
REMOTE_SERVER_NAMES = ("claude-code-remote", "Claude_Code_Remote")
REMOTE_SESSION_TOOLS = (
    "archive_session",
    "create_session",
    "get_event",
    "interrupt_session",
    "list_environments",
    "list_events",
    "list_sessions",
    "read_documentation",
    "set_session_tags",
    "set_session_title",
    "unarchive_session",
    "unwatch_url",
    "update_trigger",
    "watch_url",
)
DISABLED_PLUGINS = ("cowork-plugin-management@synced",)
USER_INVOCABLE_ONLY = "user-invocable-only"
USER_INVOCABLE_ONLY_SKILLS = (
    "anthropic-skills:chrome-browser",
    "anthropic-skills:computer-use",
    "artifact-capabilities",
    "artifact-design",
    "artifact-diagramming",
    "code-review",
    "dataviz",
    "fewer-permission-prompts",
    "init",
    "keybindings-help",
    "loop",
    "plugin-authoring",
    "run",
    "security-review",
    "session-start-hook",
    "simplify",
    "update-config",
)
DENIED_TOOLS = (
    *(
        f"mcp__{server}__{tool}"
        for server in REMOTE_SERVER_NAMES
        for tool in REMOTE_SESSION_TOOLS
    ),
    "ArtifactData",
    "CronCreate",
    "CronDelete",
    "CronList",
    "DesignSync",
    "EnterPlanMode",
    "ExitPlanMode",
    "mcp__Claude_Docs__guide",
    "mcp__github__create_repository",
    "mcp__github__fork_repository",
    "mcp__github__issue_write",
    "mcp__github__list_issue_fields",
    "mcp__github__list_issue_types",
    "mcp__github__list_issues",
    "mcp__github__request_copilot_review",
    "mcp__github__run_secret_scanning",
    "mcp__github__sub_issue_write",
    "NotebookEdit",
    "ReportFindings",
    "ScheduleWakeup",
    "SearchMcpRegistry",
    "SearchPlugins",
    "ShowOnboardingRolePicker",
    "SuggestConnectors",
    "SuggestPluginInstall",
    "SuggestSkills",
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


def run(*command: str) -> None:
    environment = {
        "DOTNET_ROOT": str(HOME / ".dotnet"),
        **os.environ,
        "PATH": TOOLCHAIN_PATH,
    }
    subprocess.run(command, check=True, stdout=sys.stderr, env=environment)


def run_pipeline(script: str) -> None:
    run("bash", "-o", "pipefail", "-c", script)


def write_atomically(path: Path, text: str) -> None:
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o644
    descriptor, staged = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".")
    try:
        with os.fdopen(descriptor, "w") as staged_file:
            staged_file.write(text)
        os.chmod(staged, mode)
        os.replace(staged, path)
    except BaseException:
        Path(staged).unlink(missing_ok=True)
        raise


def read_json(path: Path) -> JsonObject:
    try:
        text = path.read_text()
    except FileNotFoundError:
        return {}
    value = json.loads(text) if text.strip() else {}
    if not isinstance(value, dict):
        raise TypeError(f"{path} does not hold a JSON object")
    return value


def object_setting(settings: JsonObject, key: str) -> JsonObject:
    value = settings.get(key)
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise TypeError(f"Claude setting {key} is not a JSON object")
    return value


def list_setting(settings: JsonObject, key: str) -> list[JsonValue]:
    value = settings.get(key)
    if value is None:
        return []
    if not isinstance(value, list):
        raise TypeError(f"Claude setting {key} is not a JSON list")
    return value


def configure_claude_settings() -> None:
    CLAUDE_DIR.mkdir(parents=True, exist_ok=True)
    settings_path = CLAUDE_DIR / "settings.json"
    settings = read_json(settings_path)
    wanted = dict(settings)
    wanted["attribution"] = {"commit": "", "pr": "", "sessionUrl": False}
    wanted["autoMemoryEnabled"] = False
    wanted["autoCompactWindow"] = AUTO_COMPACT_WINDOW_TOKENS
    permissions = dict(object_setting(settings, "permissions"))
    denied = list_setting(permissions, "deny")
    permissions["deny"] = denied + [tool for tool in DENIED_TOOLS if tool not in denied]
    wanted["permissions"] = permissions
    wanted["skillOverrides"] = {
        **dict.fromkeys(USER_INVOCABLE_ONLY_SKILLS, USER_INVOCABLE_ONLY),
        **object_setting(settings, "skillOverrides"),
    }
    wanted["enabledPlugins"] = {
        **dict.fromkeys(DISABLED_PLUGINS, False),
        **object_setting(settings, "enabledPlugins"),
    }
    wanted["env"] = {
        **object_setting(settings, "env"),
        "CLAUDE_CODE_ACT_DONT_REDERIVE": "0",
        "CLAUDE_CODE_ARTIFACT_COMMENT_FAST_ACK": "0",
        "CLAUDE_CODE_ARTIFACT_COMMENT_FAST_ACK_FIXED": "0",
        "CLAUDE_CODE_ARTIFACT_COMMENT_RESPONDER": "0",
        "CLAUDE_CODE_ARTIFACT_COMMENTS": "0",
        "CLAUDE_CODE_ARTIFACT_COMMENTS_AUTOREACT": "0",
        "CLAUDE_CODE_BASH_OUTPUT_AUDIENCE_NOTE": "0",
        "CLAUDE_CODE_DISABLE_CFC_PROMPT": "1",
        "CLAUDE_CODE_DISABLE_EXPLORE_PLAN_AGENTS": "1",
        "CLAUDE_CODE_ENABLE_TOKEN_USAGE_ATTACHMENT": "0",
        "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1",
        "CLAUDE_CODE_SILENT_TURN_REMINDER": "0",
        "CLAUDE_CODE_TERMINAL_MCP_TOOLS": TURN_ENDING_TOOLS,
        "CLAUDE_CODE_TODO_REMINDER_MODE": "off",
        "CLAUDE_CODE_TOTAL_TOKENS_REMINDER": "off",
        "CLAUDE_CODE_TURN_UPDATES": "0",
    }
    if wanted != settings:
        write_atomically(settings_path, json.dumps(wanted, indent=2) + "\n")


def install_web_guidance_plugin() -> None:
    installed = dict_or_empty(read_json(INSTALLED_PLUGINS).get("plugins"))
    if WEB_GUIDANCE_PLUGIN in installed:
        return
    run("claude", "plugin", "marketplace", "add", "GoogleChrome/modern-web-guidance")
    run("claude", "plugin", "install", WEB_GUIDANCE_PLUGIN, "--scope", "user")


def configure_codex() -> None:
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


def install_apt_packages() -> None:
    packages = ("git-lfs", "curl", "jq", "gh", "unzip")
    if any(shutil.which(package) is None for package in packages):
        run("apt-get", "update")
        run("apt-get", "install", "-y", *packages)


def install_bun() -> None:
    if shutil.which("bun") is None and not (HOME / ".bun" / "bin" / "bun").exists():
        run_pipeline("curl -fsSL https://bun.sh/install | bash -s canary")


def install_mise() -> None:
    if shutil.which("mise") is None and not (HOME / ".local" / "bin" / "mise").exists():
        run_pipeline("curl -fsSL https://mise.run | sh")


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


def main() -> None:
    install_web_guidance_plugin()
    configure_claude_settings()
    configure_codex()
    install_cloud_tools()


if __name__ == "__main__":
    main()
