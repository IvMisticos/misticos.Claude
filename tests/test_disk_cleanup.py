import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hooks"))

import disk_cleanup
from disk_cleanup import (
    clean_up,
    cleared_bun_cache,
    cleared_caches,
    deleted_build_output,
    device_of,
)

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


@pytest.fixture
def without_tools(monkeypatch):
    monkeypatch.setattr(disk_cleanup, "output_of", lambda command: None)


def test_deletes_build_output_only_on_a_disk_that_needs_space(
    scratchpad, without_tools
):
    assert clean_up(scratchpad, {"another disk"}).build_output == []
    assert all((scratchpad / folder).exists() for folder in BUILD_OUTPUT)
    assert clean_up(scratchpad, {device_of(scratchpad)}).build_output


@pytest.fixture
def bun_cache(tmp_path, monkeypatch):
    cache = tmp_path / "bun-cache"
    monkeypatch.setenv("BUN_INSTALL_CACHE_DIR", str(cache))
    return cache


def cache_package(cache, name):
    package = cache / name
    package.mkdir(parents=True)
    (package / "index.js").write_text("x")
    return package


def test_clears_bun_packages_no_project_links_to(bun_cache, tmp_path):
    cache_package(bun_cache, "unused@1.0.0@@@1")
    linked = cache_package(bun_cache, "linked@1.0.0@@@1")
    project = tmp_path / "project" / "node_modules" / "linked"
    project.mkdir(parents=True)
    (project / "index.js").hardlink_to(linked / "index.js")
    assert cleared_bun_cache(bun_cache)
    assert sorted(entry.name for entry in bun_cache.iterdir()) == ["linked@1.0.0@@@1"]


def test_skips_a_missing_bun_cache(bun_cache):
    assert not cleared_bun_cache(bun_cache)


def test_keeps_the_bun_cache_on_macos(bun_cache, without_tools, monkeypatch):
    monkeypatch.setattr(disk_cleanup.sys, "platform", "darwin")
    unused = cache_package(bun_cache, "unused@1.0.0@@@1")
    assert cleared_caches({device_of(bun_cache)}) == []
    assert unused.exists()
