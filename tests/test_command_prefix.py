import json
import os
import subprocess
import sys

import pytest

from test_git_shim import ROOT, SHIMS, without_session_variables

COMMAND_PREFIX = ROOT / "hooks" / "command_prefix.py"
SESSION_ENVIRONMENT_SCRIPT = ROOT / "hooks" / "session_environment.sh"
FAKE_GH = """#!/usr/bin/env bash
echo "ran $*"
"""


@pytest.fixture
def project(tmp_path):
    project_dir = tmp_path / "project with 'quotes'"
    project_dir.mkdir()
    return project_dir


@pytest.fixture
def hook_environment(project):
    environment = without_session_variables(os.environ)
    environment["CLAUDE_PROJECT_DIR"] = str(project)
    return environment


def hook_output(environment, tool_input, *options):
    payload = json.dumps({"tool_name": "Bash", "tool_input": tool_input})
    output = subprocess.run(
        [sys.executable, COMMAND_PREFIX, *options],
        input=payload,
        env=environment,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return json.loads(output) if output else None


def codex_command(environment, command):
    output = hook_output(environment, {"command": command})
    return output["hookSpecificOutput"]["updatedInput"]["command"]


@pytest.fixture
def run_rewritten(tmp_path, hook_environment):
    real_bin = tmp_path / "bin"
    real_bin.mkdir()
    fake_gh = real_bin / "gh"
    fake_gh.write_text(FAKE_GH)
    fake_gh.chmod(0o755)
    shell_environment = without_session_variables(os.environ)
    shell_environment["PATH"] = f"{real_bin}:/usr/bin:/bin"
    shell_environment.pop("ALLOW_GH_PULL_REQUEST_WRITE", None)

    def run(*commands, **environment):
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


def test_allows_the_rewritten_command_in_codex(hook_environment):
    output = hook_output(hook_environment, {"command": "ls", "timeout_ms": 5})
    decision = output["hookSpecificOutput"]
    assert decision["hookEventName"] == "PreToolUse"
    assert decision["permissionDecision"] == "allow"
    assert decision["updatedInput"]["timeout_ms"] == 5
    assert decision["updatedInput"]["command"].endswith("; ls")


def test_allows_the_rewritten_command_in_cursor(hook_environment):
    tool_input = {"command": "ls", "working_directory": "/w"}
    output = hook_output(hook_environment, tool_input, "--output-shape", "cursor")
    assert output["permission"] == "allow"
    assert output["updated_input"]["working_directory"] == "/w"
    assert output["updated_input"]["command"].endswith("; ls")


@pytest.mark.parametrize("tool_input", [{}, {"command": ["ls"]}, "ls"])
def test_leaves_other_input_alone(hook_environment, tool_input):
    assert hook_output(hook_environment, tool_input) is None


def test_puts_the_shims_first_on_the_path(run_rewritten):
    result = run_rewritten("command -v gh git")
    assert result.stdout == f"{SHIMS}/gh\n{SHIMS}/git\n"


@pytest.mark.parametrize(
    "command",
    ["gh pr merge 1", "true && gh pr merge 1", "bash -c 'gh pr create --fill'"],
)
def test_denies_pull_request_writes_through_the_shim(run_rewritten, command):
    result = run_rewritten(command)
    assert result.returncode == 1
    assert "GitHub MCP tools" in result.stderr


def test_runs_other_gh_commands(run_rewritten):
    assert run_rewritten("gh pr view 1").stdout == "ran pr view 1\n"


def test_names_the_project(run_rewritten, project):
    result = run_rewritten('printf %s "$HARNESS_PROJECT_DIR"')
    assert result.stdout == str(project)


def test_records_the_identity_from_before_the_command(run_rewritten):
    result = run_rewritten(
        "GIT_AUTHOR_NAME=x printenv HARNESS_GIT_IDENTITY",
        GIT_AUTHOR_EMAIL="shell@example.com",
    )
    assert result.stdout == "|shell@example.com||\n"


def test_keeps_the_first_identity_in_a_persistent_shell(run_rewritten):
    result = run_rewritten(
        "export GIT_AUTHOR_NAME=x",
        "printenv HARNESS_GIT_IDENTITY",
        GIT_AUTHOR_EMAIL="shell@example.com",
    )
    assert result.stdout == "|shell@example.com||\n"


def test_adds_the_shims_to_the_path_once_in_a_persistent_shell(run_rewritten):
    result = run_rewritten("true", "true", 'printf %s "$PATH"')
    assert result.stdout.split(":").count(str(SHIMS)) == 1


def test_leaves_the_path_alone_when_the_shell_drops_the_arguments():
    result = subprocess.run(
        ["bash", "-c", f'. "{SESSION_ENVIRONMENT_SCRIPT}"; printf %s "$PATH"'],
        env={"PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout == "/usr/bin:/bin"
