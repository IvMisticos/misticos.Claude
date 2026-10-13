import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Protocol

import pytest
import setup_settings
from conftest import ROOT, FakeBin
from json_values import JsonObject

HOOKS = ROOT / "hooks"
ENABLED_PLUGINS = {
    "modern-web-guidance@googlechrome": True,
    "chosen-off@elsewhere": False,
}


class ConfigureSettings(Protocol):
    def __call__(self, check: bool = True) -> subprocess.CompletedProcess[bytes]: ...


def unshimmed_uv() -> str:
    directories = os.environ["PATH"].split(os.pathsep)
    unshimmed = [
        directory for directory in directories if not directory.endswith("shims")
    ]
    uv = shutil.which("uv", path=os.pathsep.join(unshimmed))
    if uv is None:
        pytest.skip("needs uv")
    return uv


@pytest.fixture(scope="module")
def uv_environment() -> tuple[str, dict[str, str]]:
    uv = unshimmed_uv()
    cache_dir = subprocess.run(
        [uv, "cache", "dir"], capture_output=True, text=True, check=True, timeout=30
    ).stdout.strip()
    environment = {**os.environ, "UV_CACHE_DIR": cache_dir}
    probe = subprocess.run(
        [
            uv,
            "run",
            "--no-project",
            "--with",
            "tomli-w",
            "python",
            "-c",
            "import tomli_w",
        ],
        env=environment,
        capture_output=True,
        check=False,
        timeout=120,
    )
    if probe.returncode != 0:
        pytest.skip("cannot fetch tomli-w")
    return uv, environment


@pytest.fixture
def configure_settings(
    home: Path, fake_bin: FakeBin, uv_environment: tuple[str, dict[str, str]]
) -> ConfigureSettings:
    uv, environment = uv_environment
    bin_dir = fake_bin("placeholder", "")

    def configure(check: bool = True) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            [uv, "run", "--script", HOOKS / "setup_settings.py"],
            env={**environment, "HOME": str(home), "PATH": f"{bin_dir}:/usr/bin:/bin"},
            capture_output=True,
            check=check,
            timeout=120,
        )

    return configure


def test_second_run_writes_nothing(
    configure_settings: ConfigureSettings, home: Path
) -> None:
    settings_path = home / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True)
    settings_path.write_text(json.dumps({"enabledPlugins": ENABLED_PLUGINS}))
    configure_settings()
    first_write = settings_path.stat().st_mtime_ns
    configure_settings()
    assert settings_path.stat().st_mtime_ns == first_write
    enabled = json.loads(settings_path.read_text())["enabledPlugins"]
    assert enabled.items() >= ENABLED_PLUGINS.items()


def test_broken_settings_are_left_alone(
    configure_settings: ConfigureSettings, home: Path
) -> None:
    settings_path = home / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True)
    settings_path.write_text("{broken")
    result = configure_settings(check=False)
    assert result.returncode != 0
    assert b"JSONDecodeError" in result.stderr
    assert settings_path.read_text() == "{broken"


def test_settings_hook_runs_every_session() -> None:
    hooks = json.loads((HOOKS / "claude.json").read_text())["hooks"]
    commands = [
        hook["command"]
        for group in hooks["SessionStart"]
        for hook in group["hooks"]
        if "setup_settings.py" in hook["command"]
    ]
    assert commands
    assert all("--once" not in command for command in commands)


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
    monkeypatch.setattr(setup_settings, "CLAUDE_DIR", tmp_path)
    settings_path = tmp_path / "settings.json"
    stored = json.dumps(settings)
    settings_path.write_text(stored)
    with pytest.raises(TypeError):
        setup_settings.configure_claude_settings()
    assert settings_path.read_text() == stored


@pytest.mark.parametrize(
    "settings",
    [
        {"permissions": None},
        {"permissions": {"deny": None}},
        {"skillOverrides": None},
        {"enabledPlugins": None},
        {"env": None},
    ],
)
def test_null_claude_settings_count_as_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, settings: JsonObject
) -> None:
    monkeypatch.setattr(setup_settings, "CLAUDE_DIR", tmp_path)
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(json.dumps(settings))
    setup_settings.configure_claude_settings()
    written = json.loads(settings_path.read_text())
    assert written["permissions"]["deny"] == list(setup_settings.DENIED_TOOLS)
