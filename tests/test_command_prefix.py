import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Protocol

import pytest
from conftest import (
    FAKE_GH,
    ROOT,
    SHIMS,
    FakeBin,
    json_at,
    run_json_hook,
    text_at,
    without_session_variables,
)
from json_values import JsonObject, JsonValue

COMMAND_PREFIX = ROOT / "hooks" / "command_prefix.py"
SESSION_ENVIRONMENT_SCRIPT = ROOT / "hooks" / "session_environment.sh"


class RunRewritten(Protocol):
    def __call__(
        self, *commands: str, **environment: str
    ) -> subprocess.CompletedProcess[str]: ...


@pytest.fixture
def project(tmp_path: Path) -> Path:
    project_dir = tmp_path / "project with 'quotes'"
    project_dir.mkdir()
    return project_dir


@pytest.fixture
def hook_environment(project: Path) -> dict[str, str]:
    environment = without_session_variables(os.environ)
    environment["CLAUDE_PROJECT_DIR"] = str(project)
    return environment


def hook_output(
    environment: dict[str, str], tool_input: JsonValue, *options: str
) -> JsonValue:
    payload: JsonObject = {"tool_name": "Bash", "tool_input": tool_input}
    return run_json_hook(COMMAND_PREFIX, payload, *options, env=environment)


def codex_command(environment: dict[str, str], command: str) -> str:
    output = hook_output(environment, {"command": command})
    return text_at(output, "hookSpecificOutput", "updatedInput", "command")


@pytest.fixture
def run_rewritten(fake_bin: FakeBin, hook_environment: dict[str, str]) -> RunRewritten:
    shell_environment = without_session_variables(os.environ)
    shell_environment["PATH"] = f"{fake_bin('gh', FAKE_GH)}:/usr/bin:/bin"

    def run(*commands: str, **environment: str) -> subprocess.CompletedProcess[str]:
        rewritten = [codex_command(hook_environment, command) for command in commands]
        return subprocess.run(
            ["bash"],
            input="\n".join(rewritten) + "\n",
            env={**shell_environment, **environment},
            capture_output=True,
            text=True,
            check=False,
        )

    return run


def test_allows_the_rewritten_command_in_codex(
    hook_environment: dict[str, str],
) -> None:
    output = hook_output(hook_environment, {"command": "ls", "timeout_ms": 5})
    decision = json_at(output, "hookSpecificOutput")
    assert json_at(decision, "hookEventName") == "PreToolUse"
    assert json_at(decision, "permissionDecision") == "allow"
    assert json_at(decision, "updatedInput", "timeout_ms") == 5


def test_allows_the_rewritten_command_in_cursor(
    hook_environment: dict[str, str],
) -> None:
    tool_input: JsonObject = {"command": "ls", "working_directory": "/w"}
    output = hook_output(hook_environment, tool_input, "--harness", "cursor")
    assert json_at(output, "permission") == "allow"
    assert json_at(output, "updated_input", "working_directory") == "/w"


@pytest.mark.parametrize("tool_input", [{}, {"command": ["ls"]}, "ls"])
def test_leaves_other_input_alone(
    hook_environment: dict[str, str], tool_input: JsonValue
) -> None:
    assert hook_output(hook_environment, tool_input) is None


def test_puts_the_shims_first_on_the_path(run_rewritten: RunRewritten) -> None:
    result = run_rewritten("command -v gh git")
    assert result.stdout == f"{SHIMS}/gh\n{SHIMS}/git\n"


def test_denies_pull_request_writes_through_the_shim(
    run_rewritten: RunRewritten,
) -> None:
    assert run_rewritten("gh pr merge 1").returncode == 1


def test_names_the_project(run_rewritten: RunRewritten, project: Path) -> None:
    result = run_rewritten('printf %s "$HARNESS_PROJECT_DIR"')
    assert result.stdout == str(project)


def test_records_the_identity_from_before_the_command(
    run_rewritten: RunRewritten,
) -> None:
    result = run_rewritten(
        "GIT_AUTHOR_NAME=x printenv HARNESS_GIT_IDENTITY",
        GIT_AUTHOR_EMAIL="shell@example.com",
    )
    assert result.stdout == "|shell@example.com||\n"


def test_keeps_the_first_identity_in_a_persistent_shell(
    run_rewritten: RunRewritten,
) -> None:
    result = run_rewritten(
        "export GIT_AUTHOR_NAME=x",
        "printenv HARNESS_GIT_IDENTITY",
        GIT_AUTHOR_EMAIL="shell@example.com",
    )
    assert result.stdout == "|shell@example.com||\n"


def test_adds_the_shims_to_the_path_once_in_a_persistent_shell(
    run_rewritten: RunRewritten,
) -> None:
    result = run_rewritten("true", "true", 'printf %s "$PATH"')
    assert result.stdout.split(":").count(str(SHIMS)) == 1


def test_leaves_the_path_alone_when_the_shell_drops_the_arguments() -> None:
    result = subprocess.run(
        ["bash", "-c", f'. "{SESSION_ENVIRONMENT_SCRIPT}"; printf %s "$PATH"'],
        env={"PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout == "/usr/bin:/bin"


def test_a_bad_argument_never_blocks_the_command(
    hook_environment: dict[str, str],
) -> None:
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": "ls"}})
    result = subprocess.run(
        [sys.executable, COMMAND_PREFIX, "--unknown"],
        input=payload,
        env=hook_environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
