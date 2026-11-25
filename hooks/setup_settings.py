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
import sys
import tomllib
from pathlib import Path

import tomli_w
from atomic_write import write_atomically
from json_values import JsonObject
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
CLOUD_AUTO_MODE: JsonObject = {
    "environment": [
        "**Host containment**: an ephemeral cloud container discarded after the session. Data files outside the repository are throwaway. Instance-metadata, node and cluster credentials are never task credentials.",
        "**Repository visibility**: assume external public unless known otherwise.",
        "**Sensitive data**: any file or store holding credentials or confidential data.",
        "**Sensitive remote targets**: any host, namespace, container, or another resource known to be in production or named `release` or `main`. A public repository takes only its own work and no secrets, sensitive data, or content from outside, internal or sensitive targets.",
    ],
    "allow": [
        "Scratch Cleanup: Deleting or overwriting files inside the session's `scratchpad/` directory. Does not cover its `agents/` subdirectory, which holds running subagents' work, or a target held in an unknown shell variable.",
        "Repository Files: Deleting or overwriting files in the session's repository in this container, by literal path or glob, and running its development servers and local tests. Discarding uncommitted work the agent did not create stays blocked.",
        "Read-Only Operations: Listing, reading, and searching files in this container, and GET requests, read-only API calls, or queries that change no state, carry no sensitive information in the URL, and return no credentials, secrets, or PII. Does not cover sensitive data locations, credential stores, cloud metadata endpoints.",
        "Dependencies: Installing with the standard command packages already declared in the repository's manifests and relevant common widely used tooling. Does not cover unpopular packages and unusual package sources.",
        "Standard Credentials: Sending a credential from the agent's own config to its intended provider.",
        "Git Push Destination: Pushing to any branch of the session's repository, and force-pushing owned branches. Does not cover sensitive remote targets.",
        "Pull Request Work: Creating a pull request in the session's repository from the agent's own branch when the task calls for one, and editing its title, body, and draft state.",
        "Multi-Agent Coordination: Starting subagents and workflows through the Agent and Workflow tools, messaging them, and replying in the conversation the task was launched from.",
        "Transient Retry: Retrying after a network error, 5xx, timeout, rate limit, lock contention, or an unexpected error from the agent's own tool. Does not cover obfuscated retries or refusal bypasses.",
        "Security Discussion: Reading, writing, or reviewing security-related code and docs. Running an exploit, scanning for credentials, or weakening a control is still judged on its own terms.",
        "Test Artifacts: Placeholder credentials and test values authored as placeholders. A value copied from a real secret is never a test artifact.",
    ],
    "soft_deny": [
        "Git Destructive: Force-pushing, deleting, or rewriting history on a branch the agent does not own, or deleting remote tags or releases.",
        "Permission Grant: Granting roles, adding collaborators, changing account or organization security settings, or sharing sensitive data more widely.",
        "Security Weaken: Disabling TLS verification, authentication, audit, sandbox, or firewall controls, or adding a way around them.",
        "Credential Exposure: Printing, copying, committing, or sending a credential anywhere but its intended provider.",
        "Untrusted Code: Running code from an unknown, uncommon or unpopular source or library, piping remote content into a shell, or running code inside an untrusted clone or archive.",
        "Self-Modification: Changing Claude Code permissions, hooks, auto mode settings, or instruction files in a way the user did not ask for.",
        "External Writes: Posting, commenting, messaging, or changing issues and records in external services when the task does not call for it.",
        "Public Exposure: Publishing a repository, sensitive data, gist, package, or tunnel, or binding a service to a public address.",
        "Irreversible Local Destruction: Deleting files that existed before the session outside the repository, scratchpad and project workspace folders.",
        "Unverifiable Deletion: Deleting remote state by a target set computed at runtime, such as a shell variable, filter, or pipeline.",
        "Real-World Transactions: Purchases, payments, or messages to people with no explicit user request.",
        "Auto-Mode Bypass: Obfuscating a blocked action, splitting it into parts, or routing it through another agent or tool with no user authorization.",
    ],
    "hard_deny": [
        "Data Exfiltration: Sending secrets, credentials, details of internals, or sensitive data to a destination that is not trusted or whose visibility may not fit the content.",
    ],
}


def read_json(path: Path) -> JsonObject:
    try:
        text = path.read_text()
    except FileNotFoundError:
        return {}
    value = json.loads(text) if text.strip() else {}
    if not isinstance(value, dict):
        raise TypeError(f"{path} does not hold a JSON object")
    return value


def setting[Kind: (dict, list)](
    settings: JsonObject, key: str, kind: type[Kind]
) -> Kind:
    value = settings.get(key)
    if value is None:
        return kind()
    if not isinstance(value, kind):
        json_name = "object" if kind is dict else "list"
        raise TypeError(f"Claude setting {key} is not a JSON {json_name}")
    return value


def plugin_choice(plugin: str) -> bool | None:
    enabled = setting(read_json(CLAUDE_SETTINGS), "enabledPlugins", dict)
    choice = enabled.get(plugin)
    return choice if isinstance(choice, bool) else None


def configure_claude_settings() -> None:
    CLAUDE_SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    settings = read_json(CLAUDE_SETTINGS)
    wanted = dict(settings)
    wanted["attribution"] = {"commit": "", "pr": "", "sessionUrl": False}
    wanted["autoMemoryEnabled"] = False
    wanted["autoCompactWindow"] = AUTO_COMPACT_WINDOW_TOKENS
    permissions = dict(setting(settings, "permissions", dict))
    denied = setting(permissions, "deny", list)
    permissions["deny"] = denied + [tool for tool in DENIED_TOOLS if tool not in denied]
    wanted["permissions"] = permissions
    wanted["skillOverrides"] = {
        **dict.fromkeys(USER_INVOCABLE_ONLY_SKILLS, USER_INVOCABLE_ONLY),
        **setting(settings, "skillOverrides", dict),
    }
    wanted["enabledPlugins"] = {
        **dict.fromkeys(DISABLED_PLUGINS, False),
        **setting(settings, "enabledPlugins", dict),
    }
    marketplaces = setting(settings, "extraKnownMarketplaces", dict)
    own_marketplace: JsonObject = {
        "source": OWN_MARKETPLACE_SOURCE,
        "autoUpdate": True,
        **setting(marketplaces, OWN_MARKETPLACE, dict),
    }
    wanted["extraKnownMarketplaces"] = {
        **marketplaces,
        OWN_MARKETPLACE: own_marketplace,
    }
    wanted["env"] = {
        **setting(settings, "env", dict),
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
    if os.environ.get("CLAUDE_CODE_REMOTE") == "true":
        wanted["autoMode"] = {
            **setting(settings, "autoMode", dict),
            **CLOUD_AUTO_MODE,
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
