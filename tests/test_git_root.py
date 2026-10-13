import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "mcp"))

from project_roots import git_root


def test_repository_top_is_the_root(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    source = tmp_path / "src" / "main.py"
    source.parent.mkdir()
    assert git_root(source) == tmp_path


def test_file_outside_repositories_is_rooted_at_its_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    monkeypatch.chdir(elsewhere)
    assert git_root(outside / "main.py") == outside


def test_file_under_the_working_directory_is_rooted_there(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "project"
    (project / "Models").mkdir(parents=True)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    monkeypatch.chdir(project)
    assert git_root(project / "Models" / "User.cs") == project
