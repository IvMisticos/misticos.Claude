from pathlib import Path

import pytest
from claude_model_cap import agent_decision
from json_values import JsonObject, JsonValue

SCOUT: JsonObject = {"subagent_type": "misticos:scout", "prompt": "find"}
ENGINEER: JsonObject = {"subagent_type": "misticos:engineer", "prompt": "build"}
CODER: JsonObject = {"subagent_type": "misticos:coder", "prompt": "build"}
WORKER: JsonObject = {"subagent_type": "general-purpose", "prompt": "find"}


@pytest.fixture(autouse=True)
def isolated_agent_lookup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / ".git").mkdir()
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("CLAUDE_CODE_SUBAGENT_MODEL", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_SUBAGENT_MODEL_FORCE", raising=False)


def decided_model(tool_input: JsonObject, caller: str | None, cwd: Path) -> JsonValue:
    decision = agent_decision(tool_input, str(cwd), caller)
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
    tmp_path: Path, tool_input: JsonObject, caller: str | None, decided: str | None
) -> None:
    assert decided_model(tool_input, caller, tmp_path) == decided


def test_requested_model_is_capped_when_the_definition_has_no_tier(
    tmp_path: Path,
) -> None:
    agents = tmp_path / ".claude" / "agents"
    agents.mkdir(parents=True)
    (agents / "x.md").write_text("---\nname: x\nmodel: Inherit\n---\n")
    worker: JsonObject = {"subagent_type": "x", "model": "opus", "prompt": "build"}
    assert decided_model(worker, "claude-sonnet-5-5", tmp_path) == "sonnet"


@pytest.mark.parametrize("tool_input", [SCOUT, WORKER], ids=["pinned", "unpinned"])
def test_requested_effort_is_dropped(tmp_path: Path, tool_input: JsonObject) -> None:
    decision = agent_decision({**tool_input, "effort": "max"}, str(tmp_path), None)
    assert decision is not None
    assert "effort" not in decision["updatedInput"]
