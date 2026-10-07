import json
import subprocess
import sys
from pathlib import Path

import pytest

GUARD = Path(__file__).resolve().parent.parent / "hooks" / "guard.py"


def guard_output(command, *options):
    payload = json.dumps({"tool_input": {"command": command}})
    return subprocess.run(
        [sys.executable, GUARD, *options],
        input=payload,
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def decision(command):
    output = guard_output(command)
    if not output:
        return "allow"
    return json.loads(output)["hookSpecificOutput"]["permissionDecision"]


def cursor_decision(command):
    return json.loads(guard_output(command, "--output-shape", "cursor"))["permission"]


@pytest.mark.parametrize(
    "command",
    [
        "git config user.name x",
        "git config --global user.email x@example.com",
        "git config --unset user.name",
        "git config set user.email x@example.com",
        "git config user.name list",
        "git config --remove-section user",
        "git config rename-section user old",
        "GIT_CONFIG_PARAMETERS=\"'user.name=x'\" git commit -m a",
        "GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=user.name GIT_CONFIG_VALUE_0=x git commit",
        "declare -x GIT_AUTHOR_NAME=x",
        "git config --global user.name $(echo x)",
        "xargs -I{} git config user.name {}",
        "sudo env GIT_AUTHOR_NAME=x git commit -m a",
        "env -u HOME GIT_AUTHOR_NAME=x git commit -m a",
        "time GIT_AUTHOR_NAME=x git commit -m a",
        "timeout 60 env GIT_AUTHOR_NAME=x git commit -m a",
        "if true; then GIT_AUTHOR_NAME=x git commit -m a; fi",
        "for f in a; do GIT_AUTHOR_NAME=x git commit -m a; done",
        "HOME=/home/git GIT_AUTHOR_NAME=x git commit -m a",
        "export GIT_AUTHOR_NAME+=x; git commit -m a",
        "git -c user.name=x commit -m a",
        "git commit --author='x <x@example.com>' -m a",
        "GIT_AUTHOR_NAME=x git commit -m a",
        "export GIT_AUTHOR_NAME=x; git commit -m a",
        "export GIT_COMMITTER_EMAIL=x@example.com && git commit -m a",
        "env GIT_AUTHOR_EMAIL=x@example.com git commit -m a",
        "bash -c 'git config user.name x'",
        "gh pr create --fill",
        "gh pr merge 1",
        "gh api -X POST repos/o/r/pulls",
        "gh api repos/o/r/pulls -f title=x",
    ],
)
def test_denies(command):
    assert decision(command) == "deny"


@pytest.mark.parametrize(
    "command",
    [
        "git status",
        "git commit -m 'set user.name docs'",
        "git config --get user.name",
        "git config get user.email",
        "git config --get-urlmatch user.name https://example.com",
        "GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=core.pager GIT_CONFIG_VALUE_0=cat git log",
        "git config --remove-section alias",
        "grep -rn GIT_AUTHOR_NAME= hooks",
        "echo GIT_AUTHOR_NAME=x",
        "rg -n GIT_AUTHOR_NAME= -t sh",
        "git log --author=x",
        "gh pr view 1",
        "gh api repos/o/r/pulls",
        "echo $GIT_AUTHOR_NAME",
        "git config user.name x # misticos.Claude.ignore",
    ],
)
def test_allows(command):
    assert decision(command) == "allow"


def test_cursor_shape_denies():
    assert cursor_decision("gh pr merge 1") == "deny"


def test_cursor_shape_allows():
    assert cursor_decision("git status") == "allow"
