import contextlib
import fcntl
import json
import os
import shutil
import subprocess
import sys
import time

import pytest
from conftest import ROOT

HOOKS = ROOT / "hooks"
FAKE_CLAUDE = """#!/usr/bin/env bash
if flock -n "$HOME/.claude/settings.lock" true; then
  echo "unlocked $*" >> "$HOME/claude-calls"
else
  echo "locked $*" >> "$HOME/claude-calls"
fi
"""
PLUGIN_ENTRY = {"plugin@elsewhere": True}


@pytest.fixture
def settings_lock(home):
    lock_path = home / ".claude" / "settings.lock"
    lock_path.parent.mkdir(parents=True)
    lock_path.touch()
    return lock_path


@contextlib.contextmanager
def held(lock_path):
    with lock_path.open("a") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        yield


def has_waiter(lock_path):
    inode = f":{lock_path.stat().st_ino} "
    with open("/proc/locks") as locks:
        return any("->" in line and inode in line for line in locks)


def wait_for_waiter(lock_path, process):
    deadline = time.monotonic() + 30
    while not has_waiter(lock_path):
        assert process.poll() is None, "setup finished without waiting for the lock"
        assert time.monotonic() < deadline, "setup never waited for the lock"
        time.sleep(0.05)


def real_uv():
    directories = os.environ["PATH"].split(os.pathsep)
    unshimmed = [
        directory for directory in directories if not directory.endswith("shims")
    ]
    uv = shutil.which("uv", path=os.pathsep.join(unshimmed))
    assert uv is not None, "the tests need uv on PATH"
    return uv


def uv_cache_dir():
    return subprocess.run(
        [real_uv(), "cache", "dir"], capture_output=True, text=True, check=True
    ).stdout.strip()


def test_plugin_install_runs_under_the_settings_lock(home, fake_bin, settings_lock):
    bin_dir = fake_bin("claude", FAKE_CLAUDE)
    (bin_dir / "flock").symlink_to(shutil.which("flock"))
    subprocess.run(
        [sys.executable, HOOKS / "setup_tools.py"],
        env={"HOME": str(home), "PATH": f"{bin_dir}:/usr/bin:/bin"},
        check=True,
    )
    calls = (home / "claude-calls").read_text().splitlines()
    assert calls == [
        "locked plugin marketplace add GoogleChrome/modern-web-guidance",
        "locked plugin install modern-web-guidance@googlechrome --scope user",
    ]


def test_settings_waits_for_the_lock_and_keeps_plugin_changes(
    home, fake_bin, settings_lock
):
    bin_dir = fake_bin("placeholder", "")
    (bin_dir / "uv").symlink_to(real_uv())
    settings_path = home / ".claude" / "settings.json"
    with held(settings_lock):
        setup = subprocess.Popen(
            ["uv", "run", "--script", HOOKS / "setup_settings.py"],
            env={
                **os.environ,
                "HOME": str(home),
                "PATH": f"{bin_dir}:/usr/bin:/bin",
                "UV_CACHE_DIR": uv_cache_dir(),
            },
        )
        wait_for_waiter(settings_lock, setup)
        settings_path.write_text(json.dumps({"enabledPlugins": PLUGIN_ENTRY}))
    assert setup.wait(timeout=60) == 0
    settings = json.loads(settings_path.read_text())
    assert settings["enabledPlugins"].items() >= PLUGIN_ENTRY.items()
    assert settings["autoMemoryEnabled"] is False
