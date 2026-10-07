import json
import subprocess
import sys
from pathlib import Path

import pytest

AGENT_SCRATCH = Path(__file__).resolve().parent.parent / "hooks" / "agent_scratch.py"
SHELL_TASK = {"id": "b1", "type": "shell", "status": "running", "command": "make"}
SUBAGENT_TASK = {"id": "a2", "type": "subagent", "status": "running"}
WORKFLOW_TASK = {"id": "w1", "type": "workflow", "status": "running"}
OWN_TASK = {"id": "a1", "type": "subagent", "status": "running"}


@pytest.fixture
def scratchpad(tmp_path):
    scratchpad = tmp_path / "scratchpad"
    (scratchpad / "agents" / "a1" / "repo" / ".git").mkdir(parents=True)
    (scratchpad / "agents" / "a2").mkdir()
    (scratchpad / "notes.md").write_text("x")
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


def contents(folder):
    return sorted(str(path.relative_to(folder)) for path in folder.iterdir())


def test_start_creates_the_folder_and_names_it(scratchpad):
    output = run_hook("SubagentStart", scratchpad_dir=str(scratchpad), agent_id="a3")
    context = output["hookSpecificOutput"]
    assert context["hookEventName"] == "SubagentStart"
    assert str(scratchpad / "agents" / "a3") in context["additionalContext"]
    assert (scratchpad / "agents" / "a3").is_dir()


@pytest.mark.parametrize("tasks", [[], [OWN_TASK]])
def test_stop_deletes_only_the_agents_folder(scratchpad, tasks):
    run_hook(
        "SubagentStop",
        scratchpad_dir=str(scratchpad),
        agent_id="a1",
        background_tasks=tasks,
    )
    assert contents(scratchpad / "agents") == ["a2"]


@pytest.mark.parametrize(
    "tasks", [[SHELL_TASK], [OWN_TASK, SUBAGENT_TASK], [WORKFLOW_TASK], None]
)
def test_stop_keeps_the_folder_while_other_work_may_use_it(scratchpad, tasks):
    run_hook(
        "SubagentStop",
        scratchpad_dir=str(scratchpad),
        agent_id="a1",
        background_tasks=tasks,
    )
    assert contents(scratchpad / "agents") == ["a1", "a2"]


def test_session_stop_deletes_every_agent_folder_when_nothing_runs(scratchpad):
    run_hook("Stop", scratchpad_dir=str(scratchpad), background_tasks=[])
    assert contents(scratchpad) == ["notes.md"]


@pytest.mark.parametrize("tasks", [[SHELL_TASK], [SUBAGENT_TASK], None])
def test_session_stop_keeps_agent_folders_while_work_runs(scratchpad, tasks):
    run_hook("Stop", scratchpad_dir=str(scratchpad), background_tasks=tasks)
    assert contents(scratchpad / "agents") == ["a1", "a2"]


@pytest.mark.parametrize("tasks", [[SHELL_TASK], None])
def test_session_end_deletes_every_agent_folder(scratchpad, tasks):
    run_hook("SessionEnd", scratchpad_dir=str(scratchpad), background_tasks=tasks)
    assert contents(scratchpad) == ["notes.md"]


@pytest.mark.parametrize("agent_id", ["", "..", "../a1", "a/b", None])
def test_ignores_agent_ids_that_are_not_a_folder_name(scratchpad, agent_id):
    for event in ("SubagentStart", "SubagentStop"):
        output = run_hook(
            event,
            scratchpad_dir=str(scratchpad),
            agent_id=agent_id,
            background_tasks=[],
        )
        assert output is None
    assert contents(scratchpad) == ["agents", "notes.md"]
    assert contents(scratchpad / "agents") == ["a1", "a2"]


@pytest.mark.parametrize("scratchpad_dir", [None, "relative/scratchpad"])
def test_ignores_a_missing_or_relative_scratchpad(tmp_path, scratchpad_dir):
    output = run_hook(
        "SubagentStart", cwd=tmp_path, scratchpad_dir=scratchpad_dir, agent_id="a1"
    )
    assert output is None
    assert list(tmp_path.iterdir()) == []
