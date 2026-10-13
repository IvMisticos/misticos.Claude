import shutil
import subprocess
from pathlib import Path
from typing import Protocol

import pytest
from conftest import ROOT, FakeBin, installed

FAKE_UV = """#!/usr/bin/env bash
echo "uv $*"
exit "${UV_STATUS-0}"
"""
SCRIPTS = {
    "settings.py": "value = 1\n",
    "tools.py": "value = 2\n",
}


class RunOnceHook(Protocol):
    def __call__(
        self,
        script: str = "settings.py",
        *,
        once: bool = True,
        path: str = ...,
        **extra_environment: str,
    ) -> subprocess.CompletedProcess[str]: ...


@pytest.fixture
def plugin_data(tmp_path: Path) -> Path:
    return tmp_path / "plugin-data"


@pytest.fixture
def scripts(tmp_path: Path) -> Path:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    shutil.copy(ROOT / "hooks" / "run.sh", scripts / "run.sh")
    for name, source in SCRIPTS.items():
        (scripts / name).write_text(source)
    return scripts


@pytest.fixture
def run_hook(
    home: Path, fake_bin: FakeBin, plugin_data: Path, scripts: Path
) -> RunOnceHook:
    bin_dir = fake_bin("uv", FAKE_UV)

    def run(
        script: str = "settings.py",
        *,
        once: bool = True,
        path: str = f"{bin_dir}:/usr/bin:/bin",
        **extra_environment: str,
    ) -> subprocess.CompletedProcess[str]:
        environment = {
            "HOME": str(home),
            "PATH": path,
            "CLAUDE_PLUGIN_DATA": str(plugin_data),
            **extra_environment,
        }
        once_flag = ["--once"] if once else []
        return subprocess.run(
            [scripts / "run.sh", *once_flag, script],
            env={name: value for name, value in environment.items() if value},
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )

    return run


def ran_uv(result: subprocess.CompletedProcess[str]) -> bool:
    return result.stdout.startswith("uv run ")


def marker_of(plugin_data: Path, script: str) -> Path:
    return plugin_data / f"{script.removesuffix('.py')}-complete"


def write_stale_marker(plugin_data: Path, script: str) -> Path:
    marker = marker_of(plugin_data, script)
    plugin_data.mkdir()
    marker.write_text("stale\n")
    return marker


def edit(scripts: Path, name: str) -> None:
    with (scripts / name).open("a") as script:
        script.write("edited = True\n")


def test_first_run_runs_the_script_and_writes_its_marker(
    run_hook: RunOnceHook, plugin_data: Path
) -> None:
    result = run_hook()
    assert result.stdout.endswith("/settings.py\n")
    assert marker_of(plugin_data, "settings.py").read_text().strip()


def test_completed_script_is_skipped(run_hook: RunOnceHook) -> None:
    run_hook()
    result = run_hook()
    assert (result.returncode, result.stdout) == (0, "")


def test_editing_the_script_reruns_it(run_hook: RunOnceHook, scripts: Path) -> None:
    run_hook()
    edit(scripts, "settings.py")
    assert ran_uv(run_hook())
    assert not ran_uv(run_hook())


def test_each_script_keeps_its_own_marker(run_hook: RunOnceHook) -> None:
    run_hook("settings.py")
    assert ran_uv(run_hook("tools.py"))


def test_stale_marker_is_rewritten(run_hook: RunOnceHook, plugin_data: Path) -> None:
    marker = write_stale_marker(plugin_data, "settings.py")
    assert ran_uv(run_hook())
    assert marker.read_text() != "stale\n"


def test_failed_run_writes_no_marker(run_hook: RunOnceHook, plugin_data: Path) -> None:
    result = run_hook(UV_STATUS="3")
    assert (ran_uv(result), result.returncode) == (True, 3)
    assert not marker_of(plugin_data, "settings.py").exists()


def test_failed_run_keeps_a_stale_marker_stale(
    run_hook: RunOnceHook, plugin_data: Path
) -> None:
    marker = write_stale_marker(plugin_data, "settings.py")
    run_hook(UV_STATUS="3")
    assert marker.read_text() == "stale\n"


def test_without_once_the_script_always_runs(run_hook: RunOnceHook) -> None:
    run_hook()
    assert ran_uv(run_hook(once=False))


def test_without_once_no_marker_is_written(
    run_hook: RunOnceHook, plugin_data: Path
) -> None:
    run_hook(once=False)
    assert not plugin_data.exists()


def test_unset_plugin_data_always_runs(run_hook: RunOnceHook) -> None:
    assert ran_uv(run_hook(CLAUDE_PLUGIN_DATA=""))
    assert ran_uv(run_hook(CLAUDE_PLUGIN_DATA=""))


def test_missing_hash_tool_runs_without_a_marker(
    run_hook: RunOnceHook, tmp_path: Path, fake_bin: FakeBin, plugin_data: Path
) -> None:
    tools = fake_bin("uv", FAKE_UV).parent / "no-hash-tools"
    tools.mkdir()
    (tools / "uv").symlink_to(tmp_path / "bin" / "uv")
    for tool in ("bash", "cat", "cut", "dirname", "mkdir"):
        (tools / tool).symlink_to(installed(tool))
    result = run_hook(path=str(tools))
    assert (ran_uv(result), result.returncode) == (True, 0)
    assert not marker_of(plugin_data, "settings.py").exists()
