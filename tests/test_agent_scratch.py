import json
import subprocess
import sys
from pathlib import Path

import pytest

AGENT_SCRATCH = Path(__file__).resolve().parent.parent / "hooks" / "agent_scratch.py"


@pytest.fixture
def scratchpad(tmp_path):
    scratchpad = tmp_path / "scratchpad"
    scratchpad.mkdir()
    return scratchpad


def run_hook(event, cwd=None, **fields):
    payload = json.dumps({"hook_event_name": event, **fields})
    output = subprocess.run(
        [sys.executable, AGENT_SCRATCH],
        input=payload,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return json.loads(output) if output else None


def test_start_creates_the_folder_and_names_it(scratchpad):
    output = run_hook("SubagentStart", scratchpad_dir=str(scratchpad), agent_id="a1")
    context = output["hookSpecificOutput"]
    assert context["hookEventName"] == "SubagentStart"
    assert str(scratchpad / "a1") in context["additionalContext"]
    assert (scratchpad / "a1").is_dir()


def test_stop_deletes_only_the_agents_folder(scratchpad):
    clone = scratchpad / "a1" / "repo" / ".git" / "objects"
    clone.mkdir(parents=True)
    (clone / "pack").write_text("x")
    (scratchpad / "a2").mkdir()
    run_hook("SubagentStop", scratchpad_dir=str(scratchpad), agent_id="a1")
    assert sorted(path.name for path in scratchpad.iterdir()) == ["a2"]


def test_stop_without_a_folder_does_nothing(scratchpad):
    assert (
        run_hook("SubagentStop", scratchpad_dir=str(scratchpad), agent_id="a1") is None
    )
    assert list(scratchpad.iterdir()) == []


@pytest.mark.parametrize("agent_id", ["", "..", "../a1", "a/b", None])
def test_ignores_agent_ids_that_are_not_a_folder_name(scratchpad, agent_id):
    (scratchpad / "a1").mkdir()
    for event in ("SubagentStart", "SubagentStop"):
        nested = scratchpad / "nested"
        assert run_hook(event, scratchpad_dir=str(nested), agent_id=agent_id) is None
    assert [path.name for path in scratchpad.iterdir()] == ["a1"]


@pytest.mark.parametrize("scratchpad_dir", [None, "relative/scratchpad"])
def test_ignores_a_missing_or_relative_scratchpad(tmp_path, scratchpad_dir):
    output = run_hook(
        "SubagentStart", cwd=tmp_path, scratchpad_dir=scratchpad_dir, agent_id="a1"
    )
    assert output is None
    assert list(tmp_path.iterdir()) == []
