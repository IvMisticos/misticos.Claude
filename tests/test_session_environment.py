import os
import subprocess
import sys
from pathlib import Path

from conftest import ROOT, without_session_variables

SESSION_ENVIRONMENT = ROOT / "hooks" / "session_environment.py"


def test_records_the_shell_identity_as_the_harness_identity(tmp_path: Path) -> None:
    env_file = tmp_path / "session.sh"
    environment = without_session_variables(os.environ)
    subprocess.run(
        [sys.executable, SESSION_ENVIRONMENT],
        env={**environment, "CLAUDE_ENV_FILE": str(env_file)},
        check=True,
    )
    recorded = subprocess.run(
        ["bash", "-c", f"source {env_file}; echo $HARNESS_GIT_IDENTITY"],
        env={**environment, "GIT_AUTHOR_EMAIL": "shell@example.com"},
        capture_output=True,
        text=True,
        check=True,
    )
    assert recorded.stdout == "|shell@example.com||\n"


def test_mise_shims_follow_the_plugin_shims_after_every_source(tmp_path: Path) -> None:
    home = tmp_path / "home"
    mise_shims = home / ".local" / "share" / "mise" / "shims"
    env_file = tmp_path / "session.sh"
    environment = {
        **without_session_variables(os.environ),
        "HOME": str(home),
        "PATH": "/usr/bin:/bin",
    }
    environment.pop("MISE_DATA_DIR", None)
    environment.pop("XDG_DATA_HOME", None)
    subprocess.run(
        [sys.executable, SESSION_ENVIRONMENT],
        env={**environment, "CLAUDE_ENV_FILE": str(env_file)},
        check=True,
    )
    sourced = subprocess.run(
        [
            "bash",
            "-c",
            f"source {env_file}; mkdir -p {mise_shims}; source {env_file}; echo $PATH",
        ],
        env=environment,
        capture_output=True,
        text=True,
        check=True,
    )
    shims = ROOT / "shims"
    assert sourced.stdout == f"{shims}:{mise_shims}:/usr/bin:/bin\n"


def test_shim_accepts_the_identity_the_session_environment_recorded(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    home = tmp_path / "home"
    env_file = tmp_path / "session.sh"
    project.mkdir()
    home.mkdir()
    environment = {
        **without_session_variables(os.environ),
        "HOME": str(home),
        "GIT_AUTHOR_NAME": "Author",
        "GIT_AUTHOR_EMAIL": "author@example.com",
        "GIT_COMMITTER_NAME": "Committer",
        "GIT_COMMITTER_EMAIL": "committer@example.com",
    }
    subprocess.run(["git", "init", "-q", str(project)], env=environment, check=True)
    subprocess.run(
        [sys.executable, SESSION_ENVIRONMENT],
        env={
            **environment,
            "CLAUDE_ENV_FILE": str(env_file),
            "CLAUDE_PROJECT_DIR": str(project),
        },
        check=True,
    )
    committed = subprocess.run(
        [
            "bash",
            "-c",
            f"source {env_file}; git -C {project} commit -q --allow-empty -m test",
        ],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert committed.returncode == 0, committed.stderr
