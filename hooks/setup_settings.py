#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = ["tomli-w"]
# ///

import json
import os
import shutil
import sys
import tempfile
import tomllib
from pathlib import Path

import tomli_w

HOME = Path.home()
CLAUDE_DIR = HOME / ".claude"
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

TURN_ENDING_TOOLS = "Agent,ReadNotifications,SendMessage,TaskStop"


def write_atomically(path, text):
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
    wanted["autoCompactWindow"] = AUTO_COMPACT_WINDOW_TOKENS
    permissions = dict(settings.get("permissions", {}))
    denied = permissions.get("deny", [])
    permissions["deny"] = denied + [tool for tool in DENIED_TOOLS if tool not in denied]
    wanted["permissions"] = permissions
    wanted["skillOverrides"] = {
        **dict.fromkeys(USER_INVOCABLE_ONLY_SKILLS, USER_INVOCABLE_ONLY),
        **settings.get("skillOverrides", {}),
    }
    wanted["enabledPlugins"] = {
        **dict.fromkeys(DISABLED_PLUGINS, False),
        **settings.get("enabledPlugins", {}),
    }
    wanted["env"] = {
        **settings.get("env", {}),
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


def main():
    configure_claude_settings()
    configure_codex()


if __name__ == "__main__":
    main()
