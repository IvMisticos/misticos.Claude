import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SHIMS = ROOT / "shims"
REAL_TOOL_LIBRARY = SHIMS / "lib" / "real_tool.sh"
FAKE_GH = """#!/usr/bin/env bash
echo "ran $*"
"""


class ReviewThread:
    def __init__(self, thread_id, comment_ids, resolved=False):
        self.id = thread_id
        self.comment_ids = comment_ids
        self.resolved = resolved

    def as_graphql(self):
        last_comment = {"databaseId": self.comment_ids[-1]}
        return {
            "id": self.id,
            "isResolved": self.resolved,
            "comments": {"nodes": [last_comment]},
        }

    def as_remote(self):
        return {
            "resolved": self.resolved,
            "outdated": False,
            "comment_ids": self.comment_ids,
        }


def graphql_review_threads(*threads, state="OPEN"):
    nodes = [thread.as_graphql() for thread in threads]
    pull_request = {"state": state, "reviewThreads": {"nodes": nodes}}
    return {"data": {"repository": {"pullRequest": pull_request}}}


def without_session_variables(environment):
    return {
        name: value
        for name, value in environment.items()
        if not name.startswith(("GIT_", "HARNESS_", "CLAUDE_", "ALLOW_"))
    }


def home_environment(home):
    return {"HOME": str(home), "PATH": "/usr/bin:/bin"}


def run_json_hook(hook, payload, *arguments, **run_options):
    output = subprocess.run(
        [sys.executable, hook, *arguments],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=True,
        **run_options,
    ).stdout
    return json.loads(output) if output else None


def json_lines(entries):
    return "".join(json.dumps(entry) + "\n" for entry in entries)


def write_json_lines(path, *entries):
    path.write_text(json_lines(entries))


def append_json_lines(path, *entries):
    with path.open("a") as lines:
        lines.write(json_lines(entries))


@pytest.fixture
def home(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    return home


@pytest.fixture
def fake_bin(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    def add(name, script):
        program = bin_dir / name
        program.write_text(script)
        program.chmod(0o755)
        return bin_dir

    return add


def real_uv_directories():
    found = subprocess.run(
        ["bash", "-c", '. "$1" && real_tool uv', "bash", REAL_TOOL_LIBRARY],
        capture_output=True,
        text=True,
        check=False,
    )
    return [os.path.dirname(found.stdout.strip())] if found.returncode == 0 else []


@pytest.fixture
def shim_runner(fake_bin):
    uv_directories = real_uv_directories()

    def runner(name, fake_script, **base_environment):
        environment = without_session_variables(os.environ)
        environment["PATH"] = os.pathsep.join(
            [str(SHIMS), str(fake_bin(name, fake_script)), "/usr/bin", "/bin"]
            + uv_directories
        )
        environment.update(base_environment)

        def run(*arguments, **extra_environment):
            return subprocess.run(
                [SHIMS / name, *arguments],
                env={**environment, **extra_environment},
                capture_output=True,
                text=True,
                check=False,
            )

        return run

    return runner
