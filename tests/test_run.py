import contextlib
import os
import signal
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from conftest import FakeBin, installed

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
def environment(fake_bin: FakeBin, home: Path) -> dict[str, str]:
    bin_dir = fake_bin("curl", FAKE_CURL)
    for tool in TOOLS:
        (bin_dir / tool).symlink_to(installed(tool))
    return {"HOME": str(home), "PATH": str(bin_dir)}


@pytest.fixture
def held_install(
    environment: dict[str, str], home: Path
) -> Iterator[subprocess.Popen[bytes]]:
    hook = start_hook({**environment, "HOLD_INSTALL": "1"})
    wait_for(home / "install-started")
    yield hook
    kill_hook(hook)


def start_hook(environment: dict[str, str]) -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        [RUN, "hook.py"],
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def kill_hook(hook: subprocess.Popen[bytes]) -> None:
    with contextlib.suppress(ProcessLookupError):
        os.killpg(hook.pid, signal.SIGKILL)
    hook.wait()


def wait_for(path: Path) -> None:
    deadline = time.monotonic() + 10
    while not path.exists():
        assert time.monotonic() < deadline, f"{path} never appeared"
        time.sleep(0.05)


def run_hook(
    environment: dict[str, str], script: str = "hook.py", timeout: float = 10
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [RUN, script],
        env=environment,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=True,
    )


def test_installs_uv_and_runs_the_hook(environment: dict[str, str]) -> None:
    assert run_hook(environment).stdout == "uv run hook.py\n"


def test_installs_uv_again_after_a_finished_install(
    environment: dict[str, str], home: Path
) -> None:
    run_hook(environment)
    (home / ".local" / "bin" / "uv").unlink()
    assert run_hook(environment).stdout == "uv run hook.py\n"


def test_waits_while_another_hook_installs_uv(
    environment: dict[str, str], held_install: subprocess.Popen[bytes]
) -> None:
    waiting = start_hook(environment)
    with pytest.raises(subprocess.TimeoutExpired):
        waiting.wait(timeout=1)
    kill_hook(waiting)


def test_installs_uv_after_another_hook_was_killed_while_installing(
    environment: dict[str, str], held_install: subprocess.Popen[bytes]
) -> None:
    kill_hook(held_install)
    assert run_hook(environment).stdout == "uv run hook.py\n"


def test_finds_scripts_next_to_itself(environment: dict[str, str]) -> None:
    script = RUN.parent / "reminder.py"
    assert run_hook(environment, "reminder.py").stdout == f"uv run {script}\n"
