import json
from pathlib import Path

import pytest
from claude_agents import AgentFolder
from claude_model_cap import agent_decision, cap_decision
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


@pytest.fixture(autouse=True)
def isolated_agent_lookup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / ".git").mkdir()
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("CLAUDE_CODE_SUBAGENT_MODEL", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_SUBAGENT_MODEL_FORCE", raising=False)


def write_definition(folder: Path, name: str, model: str) -> None:
    (folder / f"{name}.md").write_text(f"---\nname: {name}\nmodel: {model}\n---\n")


@pytest.fixture
def agents(tmp_path: Path) -> AgentFolder:
    folder = tmp_path / "agents"
    folder.mkdir()
    for name, model in PLUGIN_PINS.items():
        write_definition(folder, name, model)
    return AgentFolder(folder, "*.md", "misticos:")


def decided_model(
    tool_input: JsonObject, caller: str | None, agents: AgentFolder
) -> JsonValue:
    decision = agent_decision(tool_input, [agents], parsed_model(caller))
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
    agents: AgentFolder,
    tool_input: JsonObject,
    caller: str | None,
    decided: str | None,
) -> None:
    assert decided_model(tool_input, caller, agents) == decided


def test_requested_model_is_capped_when_the_definition_has_no_tier(
    agents: AgentFolder,
) -> None:
    write_definition(agents.path, "x", "Inherit")
    worker: JsonObject = {"subagent_type": "misticos:x", "model": "opus"}
    assert decided_model(worker, "claude-sonnet-5-5", agents) == "sonnet"


def test_default_subagent_model_applies_to_unpinned_agents(
    agents: AgentFolder, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLAUDE_CODE_SUBAGENT_MODEL", "haiku")
    assert decided_model(WORKER, "claude-opus-5-5", agents) == "haiku"


def test_forced_model_above_the_caller_is_denied(
    agents: AgentFolder, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLAUDE_CODE_SUBAGENT_MODEL", "opus")
    monkeypatch.setenv("CLAUDE_CODE_SUBAGENT_MODEL_FORCE", "1")
    decision = agent_decision(SCOUT, [agents], parsed_model("claude-sonnet-5-5"))
    assert decision == {
        "permissionDecision": "deny",
        "permissionDecisionReason": (
            "CLAUDE_CODE_SUBAGENT_MODEL_FORCE runs every subagent on opus, "
            "above your claude-sonnet-5-5. Do the work yourself."
        ),
    }


@pytest.mark.parametrize("tool_input", [SCOUT, WORKER], ids=["pinned", "unpinned"])
def test_requested_effort_is_dropped(
    agents: AgentFolder, tool_input: JsonObject
) -> None:
    decision = agent_decision({**tool_input, "effort": "max"}, [agents], None)
    assert decision is not None
    assert "effort" not in decision["updatedInput"]


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
