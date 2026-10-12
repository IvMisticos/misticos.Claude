import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hooks"))

from codex_model_cap import cap_decision

CALLER = "gpt-5-sol"


@pytest.fixture
def codex(tmp_path, monkeypatch):
    (tmp_path / ".git").mkdir()
    codex = tmp_path / ".codex"
    codex.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "home"))
    return codex


def decision(cwd, **spawn):
    return cap_decision({"model": CALLER, "cwd": str(cwd), "tool_input": spawn})


def test_role_above_the_caller_is_denied(codex):
    (codex / "config.toml").write_text('[agents.worker]\nconfig_file = "w.toml"\n')
    (codex / "w.toml").write_text('model = "gpt-5-astra"\n')
    denied = decision(codex.parent, agent_type="worker", message="go")
    assert denied["permissionDecision"] == "deny"


def test_discovered_role_is_found_by_its_name(codex):
    (codex / "agents").mkdir()
    (codex / "agents" / "w.toml").write_text('name = "worker"\nmodel = "gpt-5-astra"\n')
    denied = decision(codex.parent, agent_type="worker", message="go")
    assert denied["permissionDecision"] == "deny"


@pytest.mark.parametrize(
    "config",
    [
        "[agents.worker]\nconfig_file = 5\n",
        'agents = "worker"\n',
        "[agents\n",
        "[agents]\ndefault_subagent_model = 5\n",
    ],
)
def test_malformed_config_still_caps_the_requested_model(codex, config):
    (codex / "config.toml").write_text(config)
    capped = decision(codex.parent, model="gpt-5-astra", message="go")
    assert capped["updatedInput"]["model"] == CALLER


def test_default_subagent_model_is_capped(codex):
    (codex / "config.toml").write_text('[agents]\ndefault_subagent_model = "astra"\n')
    capped = decision(codex.parent, message="go")
    assert capped["updatedInput"]["model"] == CALLER


@pytest.fixture
def user_agents(tmp_path, codex):
    agents = tmp_path / "home" / "agents"
    agents.mkdir(parents=True)
    (agents / "bad.toml").write_bytes(b'name = "\xff"\n')
    return agents


def test_non_utf8_role_file_still_caps_the_requested_model(codex, user_agents):
    payload = {
        "model": "gpt-5-luna",
        "cwd": str(codex.parent),
        "tool_input": {"model": "gpt-5-sol", "task_name": "t"},
    }
    assert cap_decision(payload)["updatedInput"]["model"] == "gpt-5-luna"


def test_non_utf8_role_file_still_finds_other_roles(codex, user_agents):
    (user_agents / "w.toml").write_text('name = "worker"\nmodel = "gpt-5-astra"\n')
    denied = decision(codex.parent, agent_type="worker", message="go")
    assert denied["permissionDecision"] == "deny"
