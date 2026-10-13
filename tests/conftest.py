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


@pytest.fixture
def fake_bin(tmp_path: Path) -> FakeBin:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    def add(name: str, script: str) -> Path:
        program = bin_dir / name
        program.write_text(script)
        program.chmod(0o755)
        return bin_dir

    return add


@pytest.fixture
def shim_runner(fake_bin: FakeBin) -> ShimRunner:
    def runner(name: str, fake_script: str, **base_environment: str) -> ShimRun:
        environment = without_session_variables(os.environ)
        environment["PATH"] = f"{SHIMS}:{fake_bin(name, fake_script)}:/usr/bin:/bin"
        environment.update(base_environment)

        def run(
            *arguments: str, **extra_environment: str
        ) -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                [SHIMS / name, *arguments],
                env={**environment, **extra_environment},
                capture_output=True,
                text=True,
                check=False,
            )

        return run

    return runner
