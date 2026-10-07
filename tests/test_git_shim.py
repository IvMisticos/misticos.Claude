import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SHIMS = ROOT / "shims"
SESSION_ENVIRONMENT = ROOT / "hooks" / "session_environment.py"
FAKE_GIT = """#!/usr/bin/env bash
if [ "$1 $2" = "-C $MISTICOS_PROJECT_DIR" ] && [ "$3" = rev-parse ]; then
  echo "$FAKE_PROJECT_GIT_DIR"
  exit
fi
for word in "$@"; do
  if [ "$word" = rev-parse ]; then
    [ -n "$FAKE_TARGET_GIT_DIR" ] || exit 128
    echo "$FAKE_TARGET_GIT_DIR"
    exit
  fi
done
echo "ran $*"
"""


def without_session_variables(environment):
    return {
        name: value
        for name, value in environment.items()
        if not name.startswith(("GIT_", "MISTICOS_", "CLAUDE_"))
    }


@pytest.fixture
def project(tmp_path):
    project_dir = tmp_path / "project"
    (project_dir / ".git").mkdir(parents=True)
    return project_dir.resolve()


@pytest.fixture
def fixture_git_dir(tmp_path):
    git_dir = tmp_path / "fixture" / ".git"
    git_dir.mkdir(parents=True)
    return str(git_dir)


@pytest.fixture
def run_git(tmp_path, project):
    real_bin = tmp_path / "bin"
    real_bin.mkdir()
    fake_git = real_bin / "git"
    fake_git.write_text(FAKE_GIT)
    fake_git.chmod(0o755)
    base_environment = without_session_variables(os.environ)
    base_environment["PATH"] = f"{SHIMS}:{real_bin}:/usr/bin:/bin"
    base_environment["MISTICOS_PROJECT_DIR"] = str(project)
    base_environment["FAKE_PROJECT_GIT_DIR"] = str(project / ".git")
    base_environment["FAKE_TARGET_GIT_DIR"] = str(project / ".git")

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
        {"GIT_AUTHOR_NAME": "x", "ALLOW_GIT_IDENTITY_CHANGE": "1"},
    ],
)
def test_runs_with_harness_environment(run_git, environment):
    assert run_git("commit", "-m", "a", **environment).returncode == 0


def test_allows_identity_change_on_request(run_git):
    result = run_git("config", "user.name", "x", ALLOW_GIT_IDENTITY_CHANGE="1")
    assert result.returncode == 0


@pytest.mark.parametrize(
    ("arguments", "environment"),
    [
        (["config", "user.email", "test@example.com"], {}),
        (["commit", "-m", "a"], {"GIT_AUTHOR_NAME": "test"}),
        (["-C", "/tmp/fixture", "config", "user.name", "test"], {}),
    ],
)
def test_runs_identity_changes_outside_the_project(
    run_git, fixture_git_dir, arguments, environment
):
    result = run_git(*arguments, FAKE_TARGET_GIT_DIR=fixture_git_dir, **environment)
    assert result.returncode == 0


def test_runs_identity_changes_outside_any_repository(run_git):
    assert run_git("config", "user.name", "x", FAKE_TARGET_GIT_DIR="").returncode == 0


def test_denies_global_identity_changes_outside_the_project(run_git, fixture_git_dir):
    result = run_git(
        "config", "--global", "user.name", "x", FAKE_TARGET_GIT_DIR=fixture_git_dir
    )
    assert result.returncode == 1


def test_runs_identity_changes_in_repositories_nested_in_the_project(run_git, project):
    nested_git_dir = project / "nested" / ".git"
    nested_git_dir.mkdir(parents=True)
    result = run_git(
        "config", "user.name", "x", FAKE_TARGET_GIT_DIR=str(nested_git_dir)
    )
    assert result.returncode == 0


def test_records_the_shell_identity_as_the_harness_identity(tmp_path):
    env_file = tmp_path / "session.sh"
    environment = without_session_variables(os.environ)
    subprocess.run(
        [sys.executable, SESSION_ENVIRONMENT],
        env={**environment, "CLAUDE_ENV_FILE": str(env_file)},
        check=True,
    )
    recorded = subprocess.run(
        ["bash", "-c", f"source {env_file}; echo $MISTICOS_HARNESS_GIT_IDENTITY"],
        env={**environment, "GIT_AUTHOR_EMAIL": "shell@example.com"},
        capture_output=True,
        text=True,
        check=True,
    )
    assert recorded.stdout == "|shell@example.com||\n"


def test_denies_identity_changes_through_a_symlinked_project(
    run_git, project, tmp_path
):
    link = tmp_path / "link"
    link.symlink_to(project)
    result = run_git(
        "config",
        "user.name",
        "x",
        MISTICOS_PROJECT_DIR=f"{link}/",
        FAKE_PROJECT_GIT_DIR=f"{link}/.git",
    )
    assert result.returncode == 1


def test_denies_identity_changes_in_project_worktrees(run_git, project, tmp_path):
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    result = run_git("-C", str(worktree), "config", "user.name", "x")
    assert result.returncode == 1


def test_runs_identity_changes_without_a_project(run_git):
    result = run_git("commit", "-m", "a", GIT_AUTHOR_NAME="t", MISTICOS_PROJECT_DIR="")
    assert result.returncode == 0


@pytest.mark.parametrize("subcommand", ["init", "clone"])
def test_runs_repository_creation_with_an_identity(run_git, subcommand):
    assert run_git(subcommand, "/tmp/new", GIT_AUTHOR_NAME="t").returncode == 0


def test_runs_identity_changes_in_a_repository_named_by_git_dir(tmp_path):
    project_dir = tmp_path / "project"
    fixture_dir = tmp_path / "fixture"
    environment = without_session_variables(os.environ)
    environment["PATH"] = "/usr/bin:/bin"
    for repository in (project_dir, fixture_dir):
        subprocess.run(["git", "init", "-q", repository], env=environment, check=True)
    result = subprocess.run(
        [SHIMS / "git", "config", "user.name", "fixture"],
        cwd=project_dir,
        env={
            **environment,
            "PATH": f"{SHIMS}:/usr/bin:/bin",
            "MISTICOS_PROJECT_DIR": str(project_dir),
            "GIT_DIR": str(fixture_dir / ".git"),
        },
        check=False,
    )
    assert result.returncode == 0
