import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "mcp"))

from language_servers import toolchain_environment


@pytest.fixture
def isolated_home(home: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("PATH", str(home / "no-system-tools"))
    monkeypatch.delenv("DOTNET_ROOT", raising=False)
    return home


def link_dotnet_into_local_bin(home: Path, root: Path) -> None:
    root.mkdir(parents=True)
    dotnet = root / "dotnet"
    dotnet.write_text("#!/bin/sh\n")
    dotnet.chmod(0o755)
    local_bin = home / ".local" / "bin"
    local_bin.mkdir(parents=True)
    (local_bin / "dotnet").symlink_to(dotnet)


def test_dotnet_root_follows_the_linked_dotnet(isolated_home: Path) -> None:
    root = isolated_home / ".local" / "share" / "mise" / "dotnet-root"
    link_dotnet_into_local_bin(isolated_home, root)
    assert toolchain_environment()["DOTNET_ROOT"] == str(root)


def test_dotnet_root_set_by_the_user_is_kept(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    link_dotnet_into_local_bin(isolated_home, isolated_home / "linked-root")
    monkeypatch.setenv("DOTNET_ROOT", "/opt/dotnet")
    assert toolchain_environment()["DOTNET_ROOT"] == "/opt/dotnet"


@pytest.mark.usefixtures("isolated_home")
def test_dotnet_root_stays_unset_without_dotnet() -> None:
    assert "DOTNET_ROOT" not in toolchain_environment()
