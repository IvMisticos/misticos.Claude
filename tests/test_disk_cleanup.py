import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hooks"))

import disk_cleanup
from disk_cleanup import (
    CLEAR_NUGET_HTTP_CACHE,
    FIND_DOCKER_ROOT,
    LIST_NUGET_HTTP_CACHE,
    cleared_caches,
    device_of,
)


def test_clears_only_caches_on_a_disk_that_needs_space(tmp_path, monkeypatch):
    commands = []
    listings = {
        LIST_NUGET_HTTP_CACHE: f"info : http-cache: {tmp_path}\nhttp-cache: {tmp_path}",
        FIND_DOCKER_ROOT: str(tmp_path / "missing"),
    }

    def output_of(command):
        commands.append(command)
        return listings.get(command, "")

    monkeypatch.setattr(disk_cleanup, "output_of", output_of)
    assert cleared_caches({"another disk"}) == []
    assert cleared_caches({device_of(tmp_path)}) == ["the NuGet HTTP cache"]
    assert commands.count(CLEAR_NUGET_HTTP_CACHE) == 1
