import json
import subprocess
import sys
from pathlib import Path

import pytest

GUARD = Path(__file__).resolve().parent.parent / "hooks" / "guard.py"


def decision(command):
    payload = json.dumps({"tool_input": {"command": command}})
    output = subprocess.run(
        [sys.executable, GUARD],
        input=payload,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    if not output:
        return "allow"
    return json.loads(output)["hookSpecificOutput"]["permissionDecision"]


@pytest.mark.parametrize(
    "command",
    [
        "gh pr create --fill",
        "gh pr merge 1",
        "git status && gh pr merge 1",
        "bash -c 'gh pr create --fill'",
        "gh api -X POST repos/o/r/pulls",
        "gh api repos/o/r/pulls -f title=x",
    ],
)
def test_denies(command):
    assert decision(command) == "deny"


@pytest.mark.parametrize(
    "command",
    [
        "gh pr view 1",
        "gh api repos/o/r/pulls",
        "git config user.name x",
        "gh pr merge 1 # misticos.Claude.ignore",
    ],
)
def test_allows(command):
    assert decision(command) == "allow"
