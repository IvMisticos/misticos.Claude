import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Protocol

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hooks"))

from json_values import JsonObject, JsonValue

ROOT = Path(__file__).resolve().parent.parent
SHIMS = ROOT / "shims"
REAL_TOOL_LIBRARY = SHIMS / "lib" / "real_tool.sh"
SYSTEM_DIRS = ("/usr/bin", "/bin")
MISE_LOCATION_VARIABLES = frozenset({"MISE_DATA_DIR", "XDG_DATA_HOME"})
SHIM_TIMEOUT_SECONDS = 20
FAKE_GH = """#!/usr/bin/env bash
echo "ran $*"
"""

type FakeBin = Callable[[str, str], Path]


class ShimRun(Protocol):
    def __call__(
        self, *arguments: str, **extra_environment: str
    ) -> subprocess.CompletedProcess[str]: ...


class ShimRunner(Protocol):
    def __call__(
        self, name: str, fake_script: str, **base_environment: str
    ) -> ShimRun: ...


class WrappedShimRunner(Protocol):
    def __call__(
        self, name: str, fake_script: str, wrapper_entry_end: str
    ) -> ShimRun: ...


class ReviewThread:
    def __init__(
        self, thread_id: str, comment_ids: list[int], resolved: bool = False
    ) -> None:
        self.id = thread_id
        self.comment_ids = comment_ids
        self.resolved = resolved

    def as_graphql(self) -> JsonObject:
        last_comment: JsonObject = {"databaseId": self.comment_ids[-1]}
        return {
            "id": self.id,
            "isResolved": self.resolved,
            "comments": {"nodes": [last_comment]},
        }

    def as_remote(self) -> JsonObject:
        comment_ids: list[JsonValue] = [*self.comment_ids]
        return {
            "resolved": self.resolved,
            "outdated": False,
            "comment_ids": comment_ids,
        }


def graphql_review_threads(*threads: ReviewThread, state: str = "OPEN") -> JsonObject:
    nodes: list[JsonValue] = [thread.as_graphql() for thread in threads]
    pull_request: JsonObject = {"state": state, "reviewThreads": {"nodes": nodes}}
    return {"data": {"repository": {"pullRequest": pull_request}}}


def without_session_variables(environment: Mapping[str, str]) -> dict[str, str]:
    return {
        name: value
        for name, value in environment.items()
        if not name.startswith(("GIT_", "HARNESS_", "CLAUDE_", "ALLOW_"))
    }


def home_environment(home: Path) -> dict[str, str]:
    return {"HOME": str(home), "PATH": "/usr/bin:/bin"}


def shim_environment(home: Path, *path_dirs: Path | str) -> dict[str, str]:
    environment = {
        name: value
        for name, value in without_session_variables(os.environ).items()
        if name not in MISE_LOCATION_VARIABLES
    }
    environment.update(HOME=str(home), PATH=os.pathsep.join(map(str, path_dirs)))
    return environment


def run_shim(
    name: str, environment: Mapping[str, str], *arguments: str
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [SHIMS / name, *arguments],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=SHIM_TIMEOUT_SECONDS,
    )


def shim_run_for(name: str, environment: Mapping[str, str]) -> ShimRun:
    def run(
        *arguments: str, **extra_environment: str
    ) -> subprocess.CompletedProcess[str]:
        return run_shim(name, {**environment, **extra_environment}, *arguments)

    return run


def run_json_hook(
    hook: Path,
    payload: JsonObject,
    *arguments: str,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> JsonValue:
    output = subprocess.run(
        [sys.executable, hook, *arguments],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=True,
        cwd=cwd,
        env=env,
    ).stdout
    return json.loads(output) if output else None


def json_at(value: JsonValue, *keys: str) -> JsonValue:
    for key in keys:
        assert isinstance(value, dict), f"{value!r} has no {key!r}"
        value = value[key]
    return value


def text_at(value: JsonValue, *keys: str) -> str:
    text = json_at(value, *keys)
    assert isinstance(text, str), f"{text!r} is not text"
    return text


def claude_hook_commands(event: str, script: str) -> list[str]:
    hooks = json.loads((ROOT / "hooks" / "claude.json").read_text())["hooks"]
    return [
        hook["command"]
        for group in hooks[event]
        for hook in group["hooks"]
        if script in hook["command"]
    ]


def plugin_hook_command(script: str) -> str:
    return f'"${{CLAUDE_PLUGIN_ROOT}}/hooks/run.sh" {script}'


def installed(tool: str) -> str:
    path = shutil.which(tool)
    assert path is not None, f"{tool} is not installed"
    return path


def json_lines(entries: Iterable[JsonValue]) -> str:
    return "".join(json.dumps(entry) + "\n" for entry in entries)


def write_json_lines(path: Path, *entries: JsonValue) -> None:
    path.write_text(json_lines(entries))


def append_json_lines(path: Path, *entries: JsonValue) -> None:
    with path.open("a") as lines:
        lines.write(json_lines(entries))


@pytest.fixture
def home(tmp_path: Path) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    return home


def write_program(program: Path, script: str) -> None:
    program.write_text(script)
    program.chmod(0o755)


def program_writer(directory: Path) -> FakeBin:
    def add(name: str, script: str) -> Path:
        write_program(directory / name, script)
        return directory

    return add


@pytest.fixture
def fake_bin(tmp_path: Path) -> FakeBin:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    return program_writer(bin_dir)


def session_mise_shims() -> Path:
    data_home = os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share"
    return Path(os.environ.get("MISE_DATA_DIR") or Path(data_home) / "mise") / "shims"


def real_uv_directories() -> list[str]:
    path_without_mise_shims = os.pathsep.join(
        directory
        for directory in os.environ["PATH"].split(os.pathsep)
        if Path(directory) != session_mise_shims()
    )
    found = subprocess.run(
        ["bash", "-c", '. "$1" && real_tool uv', "bash", REAL_TOOL_LIBRARY],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "REAL_TOOL_PATH": path_without_mise_shims},
    )
    return [os.path.dirname(found.stdout.strip())] if found.returncode == 0 else []


@pytest.fixture
def shim_runner(home: Path, fake_bin: FakeBin) -> ShimRunner:
    uv_directories = real_uv_directories()

    def runner(name: str, fake_script: str, **base_environment: str) -> ShimRun:
        fake_dir = fake_bin(name, fake_script)
        environment = shim_environment(
            home, SHIMS, fake_dir, *SYSTEM_DIRS, *uv_directories
        )
        return shim_run_for(name, {**environment, **base_environment})

    return runner


@pytest.fixture
def wrapped_shim_runner(
    tmp_path: Path, home: Path, fake_bin: FakeBin
) -> WrappedShimRunner:
    uv_directories = real_uv_directories()
    wrapper = tmp_path / "wrapper"
    wrapper.mkdir()

    def runner(name: str, fake_script: str, wrapper_entry_end: str) -> ShimRun:
        write_program(
            wrapper / name, f'#!/usr/bin/env bash\nexec "{SHIMS / name}" "$@"\n'
        )
        fake_dir = fake_bin(name, fake_script)
        environment = shim_environment(
            home,
            str(wrapper) + wrapper_entry_end,
            fake_dir,
            *SYSTEM_DIRS,
            *uv_directories,
        )
        return shim_run_for(name, environment)

    return runner
