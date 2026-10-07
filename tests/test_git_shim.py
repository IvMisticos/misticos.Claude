import os
import subprocess
from pathlib import Path

import pytest

SHIMS = Path(__file__).resolve().parent.parent / "shims"


@pytest.fixture
def run_git(tmp_path):
    real_bin = tmp_path / "bin"
    real_bin.mkdir()
    fake_git = real_bin / "git"
    fake_git.write_text('#!/usr/bin/env bash\necho "ran $*"\n')
    fake_git.chmod(0o755)
    base_environment = {
        name: value for name, value in os.environ.items() if not name.startswith("GIT_")
    }
    base_environment.pop("MISTICOS_HARNESS_GIT_IDENTITY", None)
    base_environment["PATH"] = f"{SHIMS}:{real_bin}:/usr/bin:/bin"

    def run(*arguments, **environment):
        return subprocess.run(
            [SHIMS / "git", *arguments],
            env={**base_environment, **environment},
            capture_output=True,
            text=True,
            check=False,
        )

    return run


@pytest.mark.parametrize(
    "arguments",
    [
        ["config", "user.name", "x"],
        ["config", "--global", "user.email", "x@example.com"],
        ["config", "set", "user.email", "x@example.com"],
        ["config", "User.Name", "x"],
        ["config", "user.name", "list"],
        ["config", "--unset", "user.name"],
        ["config", "--remove-section", "user"],
        ["config", "rename-section", "user", "old"],
        ["-C", "repo", "config", "user.name", "x"],
        ["-c", "user.name=x", "commit", "-m", "a"],
        ["--config-env=user.email=EMAIL", "commit", "-m", "a"],
        ["commit", "--author=x <x@example.com>", "-m", "a"],
    ],
)
def test_denies_identity_arguments(run_git, arguments):
    result = run_git(*arguments)
    assert result.returncode == 1
    assert "keep the git identity" in result.stderr


@pytest.mark.parametrize(
    "environment",
    [
        {"GIT_AUTHOR_NAME": "x"},
        {"GIT_COMMITTER_EMAIL": "x@example.com"},
        {"GIT_CONFIG_PARAMETERS": "'user.name=x'"},
        {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "user.name"},
        {"GIT_AUTHOR_NAME": "x", "MISTICOS_HARNESS_GIT_IDENTITY": "y|||"},
    ],
)
def test_denies_identity_environment(run_git, environment):
    assert run_git("commit", "-m", "a", **environment).returncode == 1


@pytest.mark.parametrize(
    "arguments",
    [
        ["status"],
        ["config", "user.name"],
        ["config", "--get", "user.name"],
        ["config", "get", "user.email"],
        ["config", "user.email", "--show-origin"],
        ["config", "core.pager", "cat"],
        ["config", "--remove-section", "alias"],
        ["log", "--author=x"],
        ["commit", "-m", "set user.name"],
        ["-c", "core.pager=cat", "log"],
    ],
)
def test_runs_other_commands(run_git, arguments):
    result = run_git(*arguments)
    assert result.returncode == 0
    assert result.stdout == f"ran {' '.join(arguments)}\n"


@pytest.mark.parametrize(
    "environment",
    [
        {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "core.pager"},
        {"GIT_AUTHOR_NAME": "x", "MISTICOS_HARNESS_GIT_IDENTITY": "x|||"},
        {"GIT_AUTHOR_NAME": "x", "MISTICOS_ALLOW_IDENTITY_CHANGE": "1"},
    ],
)
def test_runs_with_harness_environment(run_git, environment):
    assert run_git("commit", "-m", "a", **environment).returncode == 0


def test_allows_identity_change_on_request(run_git):
    result = run_git("config", "user.name", "x", MISTICOS_ALLOW_IDENTITY_CHANGE="1")
    assert result.returncode == 0
