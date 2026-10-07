import contextlib
import os
import signal
import subprocess
import time
from pathlib import Path

import pytest

RUN = Path(__file__).resolve().parent.parent / "hooks" / "run.sh"
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
    curl = bin_dir / "curl"
    curl.write_text(FAKE_CURL)
    curl.chmod(0o755)
    return {"HOME": str(home), "PATH": f"{bin_dir}:/usr/bin:/bin"}


@pytest.fixture
def held_install(environment, home):
    hook = subprocess.Popen(
        [RUN, "hook.py"],
        env={**environment, "HOLD_INSTALL": "1"},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    wait_for(home / "install-started")
    yield hook
    with contextlib.suppress(ProcessLookupError):
        os.killpg(hook.pid, signal.SIGKILL)
    hook.wait()


def wait_for(path):
    deadline = time.monotonic() + 10
    while not path.exists():
        assert time.monotonic() < deadline, f"{path} never appeared"
        time.sleep(0.05)


def run_hook(environment, timeout=10):
    return subprocess.run(
        [RUN, "hook.py"],
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
    with pytest.raises(subprocess.TimeoutExpired):
        run_hook(environment, timeout=1)


def test_installs_uv_after_another_hook_was_killed_while_installing(
    environment, held_install
):
    os.killpg(held_install.pid, signal.SIGKILL)
    held_install.wait()
    assert run_hook(environment).stdout == "uv run hook.py\n"
