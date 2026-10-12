import os
import subprocess

import pytest
from conftest import SHIMS, without_session_variables

FAKE_GIT = """#!/usr/bin/env bash
if [ "$1 $2" = "-C $HARNESS_PROJECT_DIR" ] && [ "$3" = rev-parse ]; then
  echo "$FAKE_PROJECT_GIT_DIR"
  exit
fi
for word in "$@"; do
  [[ $word == alias.* ]] && exit 1
  if [ "$word" = rev-parse ]; then
    [ -n "$FAKE_TARGET_GIT_DIR" ] || exit 128
    echo "$FAKE_TARGET_GIT_DIR"
    exit
  fi
done
echo "ran $*"
"""


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
def run_git(shim_runner, project):
    return shim_runner(
        "git",
        FAKE_GIT,
        HARNESS_PROJECT_DIR=str(project),
        FAKE_PROJECT_GIT_DIR=str(project / ".git"),
        FAKE_TARGET_GIT_DIR=str(project / ".git"),
    )


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
    assert run_git(*arguments).returncode == 1


@pytest.mark.parametrize(
    "environment",
    [
        {"GIT_AUTHOR_NAME": "x"},
        {"GIT_COMMITTER_EMAIL": "x@example.com"},
        {"GIT_CONFIG_PARAMETERS": "'user.name=x'"},
        {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "user.name"},
        {"GIT_AUTHOR_NAME": "x", "HARNESS_GIT_IDENTITY": "y|||"},
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
        ["--config-env=core.pager=PAGER"],
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
        {"GIT_AUTHOR_NAME": "x", "HARNESS_GIT_IDENTITY": "x|||"},
        {"GIT_AUTHOR_NAME": "x", "ALLOW_GIT_IDENTITY_CHANGE": "1"},
    ],
)
def test_runs_with_harness_environment(run_git, environment):
    assert run_git("commit", "-m", "a", **environment).returncode == 0


@pytest.mark.parametrize(
    ("arguments", "environment"),
    [
        pytest.param(
            ["config", "user.name", "x"],
            {"FAKE_TARGET_GIT_DIR": ""},
            id="outside-any-repository",
        ),
        pytest.param(
            ["commit", "-m", "a"],
            {"GIT_AUTHOR_NAME": "t", "HARNESS_PROJECT_DIR": ""},
            id="without-a-project",
        ),
        pytest.param(
            ["init", "/tmp/new"], {"GIT_AUTHOR_NAME": "t"}, id="new-repository"
        ),
    ],
)
def test_runs_allowed_identity_changes(run_git, arguments, environment):
    assert run_git(*arguments, **environment).returncode == 0


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


def test_denies_identity_changes_through_a_symlinked_project(
    run_git, project, tmp_path
):
    link = tmp_path / "link"
    link.symlink_to(project)
    result = run_git(
        "config",
        "user.name",
        "x",
        HARNESS_PROJECT_DIR=f"{link}/",
        FAKE_PROJECT_GIT_DIR=f"{link}/.git",
    )
    assert result.returncode == 1


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
            "HARNESS_PROJECT_DIR": str(project_dir),
            "GIT_DIR": str(fixture_dir / ".git"),
        },
        check=False,
    )
    assert result.returncode == 0


@pytest.fixture
def run_real_git(tmp_path, home):
    project_dir = tmp_path / "real-project"
    environment = {
        **without_session_variables(os.environ),
        "HOME": str(home),
        "PATH": "/usr/bin:/bin",
    }
    subprocess.run(["git", "init", "-q", project_dir], env=environment, check=True)

    def run(*arguments):
        return subprocess.run(
            [SHIMS / "git", *arguments],
            cwd=project_dir,
            env={
                **environment,
                "PATH": f"{SHIMS}:/usr/bin:/bin",
                "HARNESS_PROJECT_DIR": str(project_dir),
            },
            capture_output=True,
            text=True,
            check=False,
        )

    return run


def denied(result):
    return result.returncode == 1 and "keep the git identity" in result.stderr


@pytest.mark.parametrize(
    "arguments",
    [
        ["-c", "alias.k=config user.name x", "k"],
        ["-c", "alias.k=config --global user.name x", "-C", "/", "k"],
        ["-c", "alias.k=-c user.email=x commit", "k", "-m", "a"],
        ["-c", "alias.k=j", "-c", "alias.j=config 'user.name' x", "k"],
        ["-c", "alias.commit=status", "commit", "--author=x <x@example.com>"],
    ],
)
def test_denies_identity_changes_through_aliases(run_real_git, arguments):
    assert denied(run_real_git(*arguments))


def test_denies_identity_changes_through_stored_aliases(run_real_git):
    assert run_real_git("config", "alias.k", "config user.name x").returncode == 0
    assert denied(run_real_git("k"))


@pytest.mark.parametrize(
    "arguments",
    [
        ["-c", "alias.k=config core.pager cat", "k"],
        ["-c", "alias.k=k", "k"],
        ["-c", "alias.k=!true", "k"],
    ],
)
def test_runs_aliases_that_keep_the_identity(run_real_git, arguments):
    assert not denied(run_real_git(*arguments))
