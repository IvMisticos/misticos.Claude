import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hooks"))

from disk_cleanup import deleted_build_output

BUILD_OUTPUT = [
    "dotnet/bin",
    "dotnet/obj",
    "bun/node_modules",
    "uv/.venv",
    "cargo/target",
]
KEPT = [
    "dotnet/App.csproj",
    "dotnet/src/Program.cs",
    "cargo/Cargo.toml",
    "tools/bin/run",
    "tools/target/notes",
    "repo/.git/obj/pack",
]


@pytest.fixture
def scratchpad(tmp_path):
    for folder in BUILD_OUTPUT:
        (tmp_path / folder / "nested" / "node_modules").mkdir(parents=True)
    for file in KEPT:
        (tmp_path / file).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / file).write_text("x")
    return tmp_path


def test_deletes_build_output(scratchpad):
    deleted = deleted_build_output(scratchpad)
    assert sorted(deleted) == sorted(scratchpad / folder for folder in BUILD_OUTPUT)
    assert not any((scratchpad / folder).exists() for folder in BUILD_OUTPUT)


def test_keeps_folders_that_only_share_a_build_output_name(scratchpad):
    deleted_build_output(scratchpad)
    assert all((scratchpad / file).exists() for file in KEPT)


def test_reports_only_folders_it_deleted(tmp_path):
    (tmp_path / "shared").mkdir()
    (tmp_path / "project").mkdir()
    (tmp_path / "project" / "node_modules").symlink_to(tmp_path / "shared")
    assert deleted_build_output(tmp_path / "project") == []
