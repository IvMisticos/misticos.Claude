import contextlib
import os
import shutil
import signal
import subprocess
import time
from pathlib import Path

import pytest

RUN = Path(__file__).resolve().parent.parent / "hooks" / "run.sh"
TOOLS = [
    "bash",
    "cat",
    "chmod",
    "dirname",
    "mkdir",
    "rm",
    "sh",
    "sleep",
    "tail",
    "touch",
]
FAKE_CURL = """#!/usr/bin/env bash
if [ -n "${HOLD_INSTALL-}" ]; then
  touch "$HOME/install-started"
  exec tail -f /dev/null
fi
cat <<'SCRIPT'
mkdir -p "$HOME/.local/bin"
printf '#!/bin/sh\\necho "uv $*"\\n' > "$HOME/.local/bin/uv"
chmod +x "$HOME/.local/bin/uv"
SCRIPT
"""


@pytest.fixture
def home(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    return home


@pytest.fixture
def environment(tmp_path, home):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for tool in TOOLS:
        (bin_dir / tool).symlink_to(shutil.which(tool))
    curl = bin_dir / "curl"
    curl.write_text(FAKE_CURL)
    curl.chmod(0o755)
    return {"HOME": str(home), "PATH": str(bin_dir)}


@pytest.fixture
def held_install(environment, home):
    hook = start_hook({**environment, "HOLD_INSTALL": "1"})
    wait_for(home / "install-started")
    yield hook
    kill_hook(hook)


def start_hook(environment):
    return subprocess.Popen(
        [RUN, "hook.py"],
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def kill_hook(hook):
    with contextlib.suppress(ProcessLookupError):
        os.killpg(hook.pid, signal.SIGKILL)
    hook.wait()


def wait_for(path):
    deadline = time.monotonic() + 10
    while not path.exists():
        assert time.monotonic() < deadline, f"{path} never appeared"
        time.sleep(0.05)


def run_hook(environment, script="hook.py", timeout=10):
    return subprocess.run(
        [RUN, script],
        env=environment,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=True,
    )


def test_installs_uv_and_runs_the_hook(environment):
    assert run_hook(environment).stdout == "uv run hook.py\n"


def test_installs_uv_again_after_a_finished_install(environment, home):
    run_hook(environment)
    (home / ".local" / "bin" / "uv").unlink()
    assert run_hook(environment).stdout == "uv run hook.py\n"


def test_waits_while_another_hook_installs_uv(environment, held_install):
    waiting = start_hook(environment)
    with pytest.raises(subprocess.TimeoutExpired):
        waiting.wait(timeout=1)
    kill_hook(waiting)


def test_installs_uv_after_another_hook_was_killed_while_installing(
    environment, held_install
):
    kill_hook(held_install)
    assert run_hook(environment).stdout == "uv run hook.py\n"


def test_finds_scripts_next_to_itself(environment):
    script = RUN.parent / "reminder.py"
    assert run_hook(environment, "reminder.py").stdout == f"uv run {script}\n"
