import json
import subprocess
import sys
import time
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


def agent_stop(tasks, left, case_id):
    fields = {"agent_id": "a1", "background_tasks": tasks}
    return pytest.param("SubagentStop", fields, left, id=f"agent-{case_id}")


def session_stop(tasks, left, case_id):
    fields = {"background_tasks": tasks}
    return pytest.param("Stop", fields, left, id=f"session-{case_id}")


def folders_and_agent_folders(scratchpad):
    paths = [*scratchpad.iterdir(), *scratchpad.glob("agents/*")]
    return sorted(str(path.relative_to(scratchpad)) for path in paths)


EVERYTHING = ["agents", "agents/a1", "agents/a2", "notes.md"]
WITHOUT_A1 = ["agents", "agents/a2", "notes.md"]
WITHOUT_AGENTS = ["notes.md"]


@pytest.mark.parametrize(
    ("event", "fields", "left"),
    [
        agent_stop([], WITHOUT_A1, "idle"),
        agent_stop([OWN_TASK], WITHOUT_A1, "only-itself"),
        agent_stop([SHELL_TASK], EVERYTHING, "shell"),
        agent_stop([OWN_TASK, SUBAGENT_TASK], EVERYTHING, "subagent"),
        agent_stop([WORKFLOW_TASK], EVERYTHING, "workflow"),
        agent_stop(None, EVERYTHING, "unknown-tasks"),
        session_stop([], WITHOUT_AGENTS, "idle"),
        session_stop([SHELL_TASK], EVERYTHING, "shell"),
        session_stop([SUBAGENT_TASK], EVERYTHING, "subagent"),
        session_stop(None, EVERYTHING, "unknown-tasks"),
    ],
)
def test_stop_deletes_agent_folders_no_running_work_uses(
    scratchpad, event, fields, left
):
    run_hook(event, scratchpad_dir=str(scratchpad), **fields)
    assert folders_and_agent_folders(scratchpad) == left


def is_emptied_soon(folder):
    deadline = time.monotonic() + 10
    while contents(folder) != ["notes.md"] and time.monotonic() < deadline:
        time.sleep(0.01)
    return contents(folder) == ["notes.md"]


@pytest.mark.parametrize("reason", ["prompt_input_exit", "logout", "other"])
def test_session_end_deletes_every_agent_folder(scratchpad, reason):
    run_hook("SessionEnd", scratchpad_dir=str(scratchpad), reason=reason)
    assert "agents" not in contents(scratchpad)
    assert is_emptied_soon(scratchpad)


@pytest.mark.parametrize("reason", ["clear", "resume"])
def test_session_end_keeps_agent_folders_that_background_tasks_outlive(
    scratchpad, reason
):
    run_hook("SessionEnd", scratchpad_dir=str(scratchpad), reason=reason)
    assert contents(scratchpad) == ["agents", "notes.md"]
    assert contents(scratchpad / "agents") == ["a1", "a2"]


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
