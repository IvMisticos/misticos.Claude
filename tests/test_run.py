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
    "date",
    "dirname",
    "ln",
    "mkdir",
    "rm",
    "sh",
    "sleep",
    "stat",
    "tail",
    "touch",
]
FAKE_MISE = """#!/usr/bin/env bash
echo "mise $*" >> "$HOME/mise-calls"
[ "$PWD" = "$HOME" ] || exit 1
installed_uv="$HOME/mise-installs/uv"
install_uv() {
  mkdir -p "$(dirname "$1")"
  printf '#!/bin/sh\\necho "uv $*"\\n' > "$1"
  chmod +x "$1"
}
case "$1" in
  config) [ -e "$HOME/mise-config" ] ;;
  which) echo "$installed_uv" ;;
  use) [ -z "${MISE_USE_FAILS-}" ] && install_uv "$installed_uv" ;;
  install) install_uv "$installed_uv" ;;
  --quiet)
    shift 4
    install_uv "$HOME/mise-x-installs/uv"
    PATH="$HOME/mise-x-installs:$PATH" exec "$@"
    ;;
esac
"""
FAKE_CURL = f"""#!/usr/bin/env bash
if [ -n "${{HOLD_INSTALL-}}" ]; then
  touch "$HOME/install-started"
  exec tail -f /dev/null
fi
cat <<'SCRIPT'
mkdir -p "$HOME/.local/bin"
cat > "$HOME/.local/bin/mise" <<'MISE'
{FAKE_MISE}MISE
chmod +x "$HOME/.local/bin/mise"
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
    environment: dict[str, str],
    script: str = "hook.py",
    timeout: float = 10,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [RUN, script],
        env=environment,
        cwd=cwd,
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
    (home / "mise-installs" / "uv").unlink()
    assert run_hook(environment).stdout == "uv run hook.py\n"


def mise_calls(home: Path) -> list[str]:
    return (home / "mise-calls").read_text().splitlines()


def test_installs_uv_through_the_global_mise_config(
    environment: dict[str, str], home: Path
) -> None:
    run_hook(environment)
    assert mise_calls(home) == [
        "mise config get --global tools.uv",
        "mise use --global uv@latest",
        "mise which uv",
    ]


def test_keeps_the_uv_version_the_user_chose(
    environment: dict[str, str], home: Path
) -> None:
    (home / "mise-config").touch()
    run_hook(environment)
    assert mise_calls(home) == [
        "mise config get --global tools.uv",
        "mise install uv",
        "mise which uv",
    ]


def test_installs_uv_from_home_inside_a_project(
    environment: dict[str, str], tmp_path: Path
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "mise.toml").write_text('[env]\nUNTRUSTED = "1"\n')
    result = run_hook(environment, cwd=project)
    assert result.stdout == "uv run hook.py\n"


def test_runs_hooks_when_the_global_mise_config_cannot_change(
    environment: dict[str, str], home: Path
) -> None:
    result = run_hook({**environment, "MISE_USE_FAILS": "1"})
    assert result.stdout == "uv run hook.py\n"
    linked_uv = (home / ".local" / "bin" / "uv").readlink()
    assert linked_uv == home / "mise-x-installs" / "uv"


@pytest.fixture
def empty_lock(home: Path) -> Path:
    lock = home / ".local" / "tool-install.pid"
    lock.parent.mkdir(parents=True)
    lock.write_text("")
    return lock


def test_waits_on_a_fresh_empty_lock(
    environment: dict[str, str], empty_lock: Path
) -> None:
    waiting = start_hook(environment)
    with pytest.raises(subprocess.TimeoutExpired):
        waiting.wait(timeout=1)
    kill_hook(waiting)
    assert empty_lock.exists()


def test_takes_over_an_old_empty_lock(
    environment: dict[str, str], empty_lock: Path
) -> None:
    an_hour_ago = time.time() - 3600
    os.utime(empty_lock, (an_hour_ago, an_hour_ago))
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
