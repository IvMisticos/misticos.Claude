import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hooks"))

from disk_cleanup import cleared_bun_cache, deleted_build_output

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


def test_clears_the_bun_cache(tmp_path, monkeypatch):
    cache = tmp_path / "bun-cache"
    (cache / "react@19").mkdir(parents=True)
    monkeypatch.setenv("BUN_INSTALL_CACHE_DIR", str(cache))
    assert cleared_bun_cache()
    assert not cache.exists()


def test_skips_a_missing_bun_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("BUN_INSTALL_CACHE_DIR", str(tmp_path / "missing"))
    assert not cleared_bun_cache()
