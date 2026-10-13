import json
import os
import shutil
import subprocess

import pytest
from conftest import ROOT

HOOKS = ROOT / "hooks"
ENABLED_PLUGINS = {
    "modern-web-guidance@googlechrome": True,
    "chosen-off@elsewhere": False,
}


def unshimmed_uv():
    directories = os.environ["PATH"].split(os.pathsep)
    unshimmed = [
        directory for directory in directories if not directory.endswith("shims")
    ]
    uv = shutil.which("uv", path=os.pathsep.join(unshimmed))
    if uv is None:
        pytest.skip("needs uv")
    return uv


@pytest.fixture(scope="module")
def uv_environment():
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
def configure_settings(home, fake_bin, uv_environment):
    uv, environment = uv_environment
    bin_dir = fake_bin("placeholder", "")

    def configure(check=True):
        return subprocess.run(
            [uv, "run", "--script", HOOKS / "setup_settings.py"],
            env={**environment, "HOME": str(home), "PATH": f"{bin_dir}:/usr/bin:/bin"},
            capture_output=True,
            check=check,
            timeout=120,
        )

    return configure


def test_second_run_writes_nothing(configure_settings, home):
    settings_path = home / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True)
    settings_path.write_text(json.dumps({"enabledPlugins": ENABLED_PLUGINS}))
    configure_settings()
    first_write = settings_path.stat().st_mtime_ns
    configure_settings()
    assert settings_path.stat().st_mtime_ns == first_write
    enabled = json.loads(settings_path.read_text())["enabledPlugins"]
    assert enabled.items() >= ENABLED_PLUGINS.items()


def test_broken_settings_are_left_alone(configure_settings, home):
    settings_path = home / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True)
    settings_path.write_text("{broken")
    result = configure_settings(check=False)
    assert result.returncode != 0
    assert b"JSONDecodeError" in result.stderr
    assert settings_path.read_text() == "{broken"


def test_settings_hook_runs_every_session():
    hooks = json.loads((HOOKS / "claude.json").read_text())["hooks"]
    commands = [
        hook["command"]
        for group in hooks["SessionStart"]
        for hook in group["hooks"]
        if "setup_settings.py" in hook["command"]
    ]
    assert commands
    assert all("--once" not in command for command in commands)
