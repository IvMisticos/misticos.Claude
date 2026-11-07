#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = ["tomli-w"]
# [tool.ty.environment]
# root = ["."]
# python = "../.venv"
# ///

import json
import shutil
import sys
import tomllib
from pathlib import Path

import tomli_w
from atomic_write import write_atomically
from json_values import JsonObject, JsonValue
from web_guidance import WEB_GUIDANCE_PLUGIN, offer_web_guidance_plugin

HOME = Path.home()
CLAUDE_SETTINGS = HOME / ".claude" / "settings.json"
CODEX_DIR = HOME / ".codex"
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
OWN_MARKETPLACE = "misticos"
OWN_MARKETPLACE_SOURCE: JsonObject = {
    "source": "github",
    "repo": "IvMisticos/misticos.Claude",
}
USER_INVOCABLE_ONLY = "user-invocable-only"
USER_INVOCABLE_ONLY_SKILLS = (
    "anthropic-skills:chrome-browser",
    "anthropic-skills:computer-use",
    "artifact-capabilities",
    "artifact-design",
    "artifact-diagramming",
    "artifact-pr-review",
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

TURN_ENDING_TOOLS = "Agent,ReadNotifications,SendMessage,TaskStop"


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


def plugin_choice(plugin: str) -> bool | None:
    enabled = object_setting(read_json(CLAUDE_SETTINGS), "enabledPlugins")
    choice = enabled.get(plugin)
    return choice if isinstance(choice, bool) else None


def configure_claude_settings() -> None:
    CLAUDE_SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    settings = read_json(CLAUDE_SETTINGS)
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
    marketplaces = object_setting(settings, "extraKnownMarketplaces")
    own_marketplace: JsonObject = {
        "source": OWN_MARKETPLACE_SOURCE,
        "autoUpdate": True,
        **object_setting(marketplaces, OWN_MARKETPLACE),
    }
    wanted["extraKnownMarketplaces"] = {
        **marketplaces,
        OWN_MARKETPLACE: own_marketplace,
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
        "CLAUDE_CODE_DISABLE_FILE_MENTIONS": "1",
        "CLAUDE_CODE_ENABLE_TOKEN_USAGE_ATTACHMENT": "0",
        "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1",
        "CLAUDE_CODE_FORK_SUBAGENT": "0",
        "CLAUDE_CODE_SILENT_TURN_REMINDER": "0",
        "CLAUDE_CODE_TERMINAL_MCP_TOOLS": TURN_ENDING_TOOLS,
        "CLAUDE_CODE_TODO_REMINDER_MODE": "off",
        "CLAUDE_CODE_TOTAL_TOKENS_REMINDER": "off",
        "CLAUDE_CODE_TURN_UPDATES": "0",
    }
    if wanted != settings:
        write_atomically(CLAUDE_SETTINGS, json.dumps(wanted, indent=2) + "\n")


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


def main() -> None:
    web_guidance_choice = plugin_choice(WEB_GUIDANCE_PLUGIN)
    try:
        offer_web_guidance_plugin(web_guidance_choice)
    finally:
        configure_claude_settings()
        configure_codex()


if __name__ == "__main__":
    main()
