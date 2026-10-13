from pathlib import Path

import pytest
from codex_model_cap import cap_decision
from hook_io import PreToolUseDecision
from json_values import JsonObject, JsonValue

CALLER = "gpt-5-sol"


@pytest.fixture
def codex(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / ".git").mkdir()
    codex = tmp_path / ".codex"
    codex.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "home"))
    return codex


def decision(cwd: Path, **spawn: JsonValue) -> PreToolUseDecision:
    decided = cap_decision({"model": CALLER, "cwd": str(cwd), "tool_input": spawn})
    assert decided is not None
    return decided


def test_role_above_the_caller_is_denied(codex: Path) -> None:
    (codex / "config.toml").write_text('[agents.worker]\nconfig_file = "w.toml"\n')
    (codex / "w.toml").write_text('model = "gpt-5-astra"\n')
    denied = decision(codex.parent, agent_type="worker", message="go")
    assert denied["permissionDecision"] == "deny"


def test_discovered_role_is_found_by_its_name(codex: Path) -> None:
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
def test_malformed_config_still_caps_the_requested_model(
    codex: Path, config: str
) -> None:
    (codex / "config.toml").write_text(config)
    capped = decision(codex.parent, model="gpt-5-astra", message="go")
    assert capped["updatedInput"]["model"] == CALLER


def test_default_subagent_model_is_capped(codex: Path) -> None:
    (codex / "config.toml").write_text('[agents]\ndefault_subagent_model = "astra"\n')
    capped = decision(codex.parent, message="go")
    assert capped["updatedInput"]["model"] == CALLER


@pytest.fixture
def user_agents(tmp_path: Path, codex: Path) -> Path:
    agents = tmp_path / "home" / "agents"
    agents.mkdir(parents=True)
    (agents / "bad.toml").write_bytes(b'name = "\xff"\n')
    return agents


def test_non_utf8_role_file_still_caps_the_requested_model(
    codex: Path, user_agents: Path
) -> None:
    payload: JsonObject = {
        "model": "gpt-5-luna",
        "cwd": str(codex.parent),
        "tool_input": {"model": "gpt-5-sol", "task_name": "t"},
    }
    capped = cap_decision(payload)
    assert capped is not None
    assert capped["updatedInput"]["model"] == "gpt-5-luna"


def test_non_utf8_role_file_still_finds_other_roles(
    codex: Path, user_agents: Path
) -> None:
    (user_agents / "w.toml").write_text('name = "worker"\nmodel = "gpt-5-astra"\n')
    denied = decision(codex.parent, agent_type="worker", message="go")
    assert denied["permissionDecision"] == "deny"
