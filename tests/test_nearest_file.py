import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "mcp"))

from project_roots import nearest_file_with


def touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()
    return path


def test_nearest_match_wins(tmp_path: Path) -> None:
    touch(tmp_path / "repo" / "All.sln")
    inner = touch(tmp_path / "repo" / "app" / "App.sln")
    source = tmp_path / "repo" / "app" / "src" / "main.cs"
    assert nearest_file_with(source, (".sln",), tmp_path / "repo") == inner


def test_search_stops_at_the_repository(tmp_path: Path) -> None:
    touch(tmp_path / "Outside.sln")
    source = tmp_path / "repo" / "main.cs"
    assert nearest_file_with(source, (".sln",), tmp_path / "repo") is None


def test_file_outside_the_repository_has_no_match(tmp_path: Path) -> None:
    touch(tmp_path / "Outside.sln")
    source = tmp_path / "main.cs"
    assert nearest_file_with(source, (".sln",), tmp_path / "repo") is None
