import os
import subprocess
import sys

from conftest import ROOT, without_session_variables

SESSION_ENVIRONMENT = ROOT / "hooks" / "session_environment.py"


def test_records_the_shell_identity_as_the_harness_identity(tmp_path):
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
