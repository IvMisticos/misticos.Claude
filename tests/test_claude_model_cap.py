import copy
import json
from pathlib import Path

import pytest
from claude_agents import AgentFolder
from claude_model_cap import SubagentConfig, agent_decision, cap_decision
from json_values import JsonObject, JsonValue
from model_cap import parsed_model

PLUGIN_PINS = {"scout": "haiku", "engineer": "opus", "coder": "sonnet"}
SCOUT: JsonObject = {"subagent_type": "misticos:scout", "prompt": "find"}
ENGINEER: JsonObject = {"subagent_type": "misticos:engineer", "prompt": "build"}
CODER: JsonObject = {"subagent_type": "misticos:coder", "prompt": "build"}
WORKER: JsonObject = {"subagent_type": "general-purpose", "prompt": "find"}
SESSION_CALL: JsonObject = {
    "tool_name": "mcp__claude-code-remote__create_session",
    "tool_input": {"model": "opus"},
}


@pytest.fixture
def isolated_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / ".git").mkdir()
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("CLAUDE_CODE_SUBAGENT_MODEL", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_SUBAGENT_MODEL_FORCE", raising=False)


def write_definition(folder: Path, name: str, model: str) -> None:
    (folder / f"{name}.md").write_text(f"---\nname: {name}\nmodel: {model}\n---\n")


@pytest.fixture
def project_agents(tmp_path: Path) -> Path:
    folder = tmp_path / "project"
    folder.mkdir()
    return folder


@pytest.fixture
def config(tmp_path: Path, project_agents: Path) -> SubagentConfig:
    plugin_agents = tmp_path / "plugin"
    plugin_agents.mkdir()
    for name, model in PLUGIN_PINS.items():
        write_definition(plugin_agents, name, model)
    folders = [
        AgentFolder(project_agents, "**/*.md"),
        AgentFolder(plugin_agents, "*.md", "misticos:"),
    ]
    return SubagentConfig(folders, default_model=None, model_forced=False)


def decided_model(
    tool_input: JsonObject, caller: str | None, config: SubagentConfig
) -> JsonValue:
    decision = agent_decision(tool_input, parsed_model(caller), config)
    return decision["updatedInput"]["model"] if decision else None


@pytest.mark.parametrize(
    ("tool_input", "caller", "decided"),
    [
        pytest.param(SCOUT, "claude-opus-5-5", "haiku", id="pinned-model"),
        pytest.param(
            {**SCOUT, "model": "opus"}, "claude-opus-5-5", "haiku", id="pin-wins"
        ),
        pytest.param(ENGINEER, "claude-sonnet-5-5", "sonnet", id="pin-capped"),
        pytest.param(
            {**WORKER, "model": "haiku"}, "claude-opus-5-5", None, id="unpinned"
        ),
        pytest.param({**CODER, "model": "opus"}, None, "sonnet", id="unknown-caller"),
    ],
)
def test_decides_the_agent_model(
    config: SubagentConfig,
    tool_input: JsonObject,
    caller: str | None,
    decided: str | None,
) -> None:
    assert decided_model(tool_input, caller, config) == decided


def test_requested_model_is_capped_when_the_definition_has_no_tier(
    config: SubagentConfig, project_agents: Path
) -> None:
    write_definition(project_agents, "x", "Inherit")
    worker: JsonObject = {"subagent_type": "x", "model": "opus", "prompt": "build"}
    assert decided_model(worker, "claude-sonnet-5-5", config) == "sonnet"


@pytest.mark.parametrize(
    ("default_model", "caller", "decided"),
    [
        pytest.param("haiku", "claude-opus-5-5", "haiku", id="below-the-caller"),
        pytest.param("opus", "claude-sonnet-5-5", "sonnet", id="capped"),
    ],
)
def test_default_subagent_model_applies_to_unpinned_agents(
    config: SubagentConfig, default_model: str, caller: str, decided: str
) -> None:
    with_default = copy.replace(config, default_model=default_model)
    assert decided_model(WORKER, caller, with_default) == decided


def test_forced_model_above_the_caller_is_denied(config: SubagentConfig) -> None:
    forced = copy.replace(config, default_model="opus", model_forced=True)
    decision = agent_decision(SCOUT, parsed_model("claude-sonnet-5-5"), forced)
    assert decision is not None
    assert decision["permissionDecision"] == "deny"
    assert decision["permissionDecisionReason"] == (
        "With CLAUDE_CODE_SUBAGENT_MODEL_FORCE set, every subagent runs on opus, "
        "above your claude-sonnet-5-5. Do the work yourself."
    )


@pytest.mark.parametrize("tool_input", [SCOUT, WORKER], ids=["pinned", "unpinned"])
def test_requested_effort_is_dropped(
    config: SubagentConfig, tool_input: JsonObject
) -> None:
    decision = agent_decision({**tool_input, "effort": "max"}, None, config)
    assert decision is not None
    assert "effort" not in decision["updatedInput"]


@pytest.mark.usefixtures("isolated_environment")
@pytest.mark.parametrize(
    "transcript_field",
    [pytest.param({}, id="missing"), pytest.param({"transcript_path": 5}, id="number")],
)
def test_subagent_without_a_transcript_path_gets_the_pinned_model(
    tmp_path: Path, transcript_field: JsonObject
) -> None:
    payload: JsonObject = {
        "tool_name": "Agent",
        "tool_input": SCOUT,
        "agent_id": "a1",
        "cwd": str(tmp_path),
        **transcript_field,
    }
    decision = cap_decision(payload)
    assert decision is not None
    assert decision["updatedInput"]["model"] == "haiku"


def test_reads_the_transcript_only_at_an_absolute_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    transcript = tmp_path / "main.jsonl"
    entry = {"type": "assistant", "message": {"model": "claude-haiku-4-5"}}
    transcript.write_text(json.dumps(entry) + "\n")
    assert cap_decision({**SESSION_CALL, "transcript_path": transcript.name}) is None
    absolute = cap_decision({**SESSION_CALL, "transcript_path": str(transcript)})
    assert absolute == {"updatedInput": {"model": "claude-haiku-4-5"}}
