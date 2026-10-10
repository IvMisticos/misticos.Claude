import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hooks"))

from claude_model_cap import agent_decision

SCOUT = {"subagent_type": "misticos:scout", "prompt": "find"}
ENGINEER = {"subagent_type": "misticos:engineer", "prompt": "build"}
CODER = {"subagent_type": "misticos:coder", "prompt": "build"}
WORKER = {"subagent_type": "general-purpose", "prompt": "find"}


def decided_model(tool_input, caller, cwd):
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
def test_decides_the_agent_model(tmp_path, tool_input, caller, decided):
    assert decided_model(tool_input, caller, tmp_path) == decided


def test_requested_model_is_capped_when_the_definition_has_no_tier(tmp_path):
    agents = tmp_path / ".claude" / "agents"
    agents.mkdir(parents=True)
    (agents / "x.md").write_text("---\nname: x\nmodel: Inherit\n---\n")
    (tmp_path / ".git").mkdir()
    worker = {"subagent_type": "x", "model": "opus", "prompt": "build"}
    assert decided_model(worker, "claude-sonnet-5-5", tmp_path) == "sonnet"
