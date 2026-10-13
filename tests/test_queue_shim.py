import os
import subprocess
import sys

import pytest
from conftest import SHIMS

PRINT_ENVIRONMENT = """#!/usr/bin/env bash
echo "PATH=$PATH"
echo "VIRTUAL_ENV=${VIRTUAL_ENV-}"
"""


@pytest.fixture
def run_cargo(shim_runner):
    return shim_runner("cargo", PRINT_ENVIRONMENT)


@pytest.fixture
def inside_project_with_venv(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    subprocess.run(
        [sys.executable, "-m", "venv", "--without-pip", project / ".venv"], check=True
    )
    monkeypatch.chdir(project)


@pytest.mark.usefixtures("inside_project_with_venv")
def test_tool_sees_the_callers_environment(run_cargo):
    result = run_cargo("--version")

    assert result.returncode == 0, result.stderr
    seen = dict(line.split("=", 1) for line in result.stdout.splitlines())
    assert seen["PATH"].split(os.pathsep)[0] == str(SHIMS)
    assert seen["VIRTUAL_ENV"] == os.environ.get("VIRTUAL_ENV", "")
