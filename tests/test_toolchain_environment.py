import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "mcp"))

from language_servers import LANGUAGE_SERVERS, install_command, toolchain_environment


@pytest.fixture
def isolated_home(home: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("PATH", str(home / "no-system-tools"))
    monkeypatch.delenv("DOTNET_ROOT", raising=False)
    return home


def make_dotnet_root(root: Path) -> None:
    (root / "host" / "fxr").mkdir(parents=True)


def link_dotnet_into_local_bin(home: Path, root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    dotnet = root / "dotnet"
    dotnet.write_text("#!/bin/sh\n")
    dotnet.chmod(0o755)
    local_bin = home / ".local" / "bin"
    local_bin.mkdir(parents=True)
    (local_bin / "dotnet").symlink_to(dotnet)


def test_dotnet_root_follows_the_linked_dotnet(isolated_home: Path) -> None:
    root = isolated_home / ".local" / "share" / "mise" / "dotnet-root"
    make_dotnet_root(root)
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


def add_fake_mise(home: Path, script: str) -> Path:
    local_bin = home / ".local" / "bin"
    local_bin.mkdir(parents=True, exist_ok=True)
    mise = local_bin / "mise"
    mise.write_text(script)
    mise.chmod(0o755)
    return mise


def test_dotnet_root_comes_from_mise_when_dotnet_is_not_linked(
    isolated_home: Path,
) -> None:
    root = isolated_home / "mise-dotnet"
    make_dotnet_root(root)
    add_fake_mise(isolated_home, f'#!/bin/sh\n[ "$1" = where ] && echo "{root}"\n')
    assert toolchain_environment()["DOTNET_ROOT"] == str(root)


def test_missing_installer_runs_through_mise(isolated_home: Path) -> None:
    mise = add_fake_mise(isolated_home, "#!/bin/sh\nexit 1\n")
    spec = LANGUAGE_SERVERS["csharp"]
    assert install_command(spec, toolchain_environment()) == [
        str(mise),
        "--quiet",
        "x",
        "dotnet",
        "--",
        *spec["install"],
    ]


@pytest.mark.usefixtures("isolated_home")
def test_missing_installer_without_mise_is_reported() -> None:
    with pytest.raises(RuntimeError, match="dotnet is not installed"):
        install_command(LANGUAGE_SERVERS["csharp"], toolchain_environment())


def test_a_file_named_dotnet_outside_a_dotnet_root_is_ignored(
    isolated_home: Path,
) -> None:
    link_dotnet_into_local_bin(isolated_home, isolated_home / "not-a-root")
    assert "DOTNET_ROOT" not in toolchain_environment()
