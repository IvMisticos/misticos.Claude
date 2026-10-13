import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Protocol

import pytest
import setup
from conftest import ROOT, FakeBin, installed
from json_values import JsonObject

HOOKS = ROOT / "hooks"
FAKE_UV = """#!/usr/bin/env bash
echo "uv $*"
exit "${UV_STATUS-0}"
"""


class RunSetupHook(Protocol):
    def __call__(
        self,
        script: str = "setup.py",
        path: str | None = None,
        **extra_environment: str,
    ) -> subprocess.CompletedProcess[str]: ...


@pytest.fixture
def plugin_data(tmp_path: Path) -> Path:
    return tmp_path / "plugin-data"


@pytest.fixture
def marker(plugin_data: Path) -> Path:
    return plugin_data / "setup-complete"


@pytest.fixture
def current_key() -> str:
    digest = hashlib.sha256((HOOKS / "setup.py").read_bytes()).hexdigest()
    return f"{digest}\n"


@pytest.fixture
def run_hook(
    tmp_path: Path, home: Path, fake_bin: FakeBin, plugin_data: Path
) -> RunSetupHook:
    bin_dir = fake_bin("uv", FAKE_UV)
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    shutil.copy(HOOKS / "run.sh", scripts / "run.sh")
    shutil.copy(HOOKS / "setup.py", scripts / "setup.py")
    (scripts / "other.py").touch()

    def run(
        script: str = "setup.py",
        path: str | None = None,
        **extra_environment: str,
    ) -> subprocess.CompletedProcess[str]:
        environment = {
            "HOME": str(home),
            "PATH": path or f"{bin_dir}:/usr/bin:/bin",
            "CLAUDE_PLUGIN_DATA": str(plugin_data),
            **extra_environment,
        }
        return subprocess.run(
            [scripts / "run.sh", script],
            env={name: value for name, value in environment.items() if value},
            capture_output=True,
            text=True,
            check=False,
        )

    return run


def ran_uv(result: subprocess.CompletedProcess[str]) -> bool:
    return result.stdout.startswith("uv run ")


def write_marker(plugin_data: Path, marker: Path, content: str) -> None:
    plugin_data.mkdir()
    marker.write_text(content)


def test_matching_marker_skips_setup(
    run_hook: RunSetupHook, plugin_data: Path, marker: Path, current_key: str
) -> None:
    write_marker(plugin_data, marker, current_key)
    result = run_hook()
    assert (result.returncode, result.stdout) == (0, "")


def test_missing_marker_runs_setup_and_writes_it(
    run_hook: RunSetupHook, marker: Path, current_key: str
) -> None:
    assert ran_uv(run_hook())
    assert marker.read_text() == current_key


def test_stale_marker_runs_setup_and_rewrites_it(
    run_hook: RunSetupHook, plugin_data: Path, marker: Path, current_key: str
) -> None:
    write_marker(plugin_data, marker, "stale\n")
    assert ran_uv(run_hook())
    assert marker.read_text() == current_key


def test_failed_setup_writes_no_marker(run_hook: RunSetupHook, marker: Path) -> None:
    result = run_hook(UV_STATUS="3")
    assert (ran_uv(result), result.returncode) == (True, 3)
    assert not marker.exists()


def test_failed_setup_keeps_a_stale_marker_stale(
    run_hook: RunSetupHook, plugin_data: Path, marker: Path
) -> None:
    write_marker(plugin_data, marker, "stale\n")
    run_hook(UV_STATUS="3")
    assert marker.read_text() == "stale\n"


def test_other_scripts_never_skip(
    run_hook: RunSetupHook, plugin_data: Path, marker: Path, current_key: str
) -> None:
    write_marker(plugin_data, marker, current_key)
    assert ran_uv(run_hook("other.py"))


def test_other_scripts_write_no_marker(run_hook: RunSetupHook, marker: Path) -> None:
    run_hook("other.py")
    assert not marker.exists()


def test_unset_plugin_data_always_runs_setup(
    run_hook: RunSetupHook, tmp_path: Path
) -> None:
    assert ran_uv(run_hook(CLAUDE_PLUGIN_DATA=""))
    assert not (tmp_path / "setup-complete").exists()


def test_missing_hash_tool_runs_setup_without_a_marker(
    run_hook: RunSetupHook, tmp_path: Path, fake_bin: FakeBin, marker: Path
) -> None:
    tools = fake_bin("uv", FAKE_UV).parent / "no-hash-tools"
    tools.mkdir()
    (tools / "uv").symlink_to(tmp_path / "bin" / "uv")
    for tool in ("bash", "cat", "cut", "dirname", "mkdir"):
        (tools / tool).symlink_to(installed(tool))
    result = run_hook(path=str(tools))
    assert (ran_uv(result), result.returncode) == (True, 0)
    assert not marker.exists()


@pytest.mark.parametrize(
    "settings",
    [
        {"permissions": ["Bash"]},
        {"permissions": {"deny": "Bash"}},
        {"skillOverrides": "x"},
        {"enabledPlugins": 1},
        {"env": ["A=1"]},
    ],
)
def test_malformed_claude_settings_stay_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, settings: JsonObject
) -> None:
    monkeypatch.setattr(setup, "CLAUDE_DIR", tmp_path)
    settings_path = tmp_path / "settings.json"
    stored = json.dumps(settings)
    settings_path.write_text(stored)
    with pytest.raises(TypeError):
        setup.configure_claude_settings()
    assert settings_path.read_text() == stored
