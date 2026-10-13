import os
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import SHIMS, ShimRun, ShimRunner

PRINT_ENVIRONMENT = """#!/usr/bin/env bash
echo "PATH=$PATH"
echo "VIRTUAL_ENV=${VIRTUAL_ENV-}"
"""

UV_WITHOUT_PYTHON = f"""#!/usr/bin/env bash
here=$(dirname "$0")
case " $* " in
  *" python install "*)
    echo "$*" > "$here/uv-install-arguments"
    ;;
  *" python find "*)
    [ -e "$here/uv-install-arguments" ] || exit 2
    echo {sys.executable}
    ;;
esac
"""


@pytest.fixture
def run_cargo(shim_runner: ShimRunner) -> ShimRun:
    return shim_runner("cargo", PRINT_ENVIRONMENT)


@pytest.fixture
def inside_project_with_venv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = tmp_path / "project"
    project.mkdir()
    subprocess.run(
        [sys.executable, "-m", "venv", "--without-pip", project / ".venv"], check=True
    )
    monkeypatch.chdir(project)


@pytest.mark.usefixtures("inside_project_with_venv")
def test_tool_sees_the_callers_environment(run_cargo: ShimRun) -> None:
    result = run_cargo("--version")

    assert result.returncode == 0, result.stderr
    seen = dict(line.split("=", 1) for line in result.stdout.splitlines())
    assert seen["PATH"].split(os.pathsep)[0] == str(SHIMS)
    assert seen["VIRTUAL_ENV"] == os.environ.get("VIRTUAL_ENV", "")


@pytest.fixture
def inside_project_with_broken_uv_config(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    (project / "uv.toml").write_text("this is not toml [\n")
    monkeypatch.chdir(project)


@pytest.mark.usefixtures("inside_project_with_broken_uv_config")
def test_missing_python_installs_outside_the_project(run_cargo, fake_bin):
    bin_dir = fake_bin("uv", UV_WITHOUT_PYTHON)

    result = run_cargo("--version")

    assert result.returncode == 0, result.stderr
    install_arguments = (bin_dir / "uv-install-arguments").read_text().split()
    assert install_arguments[:2] == ["--directory", "/"]
