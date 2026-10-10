import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hooks"))

from claude_model_cap import agent_decision


def decided_model(tool_input, caller, cwd):
    decision = agent_decision(tool_input, str(cwd), caller)
    return decision["updatedInput"]["model"] if decision else None


def test_plugin_agent_runs_on_its_pinned_model(tmp_path):
    scout = {"subagent_type": "misticos:scout", "prompt": "find"}
    assert decided_model(scout, "claude-opus-5-5", tmp_path) == "haiku"


def test_pinned_model_wins_over_a_requested_model(tmp_path):
    scout = {"subagent_type": "misticos:scout", "model": "opus", "prompt": "find"}
    assert decided_model(scout, "claude-opus-5-5", tmp_path) == "haiku"


def test_pinned_model_stays_capped_at_the_caller(tmp_path):
    engineer = {"subagent_type": "misticos:engineer", "prompt": "build"}
    assert decided_model(engineer, "claude-sonnet-5-5", tmp_path) == "sonnet"


def test_requested_model_still_applies_to_unpinned_agents(tmp_path):
    worker = {"subagent_type": "general-purpose", "model": "haiku", "prompt": "find"}
    assert decided_model(worker, "claude-opus-5-5", tmp_path) is None
