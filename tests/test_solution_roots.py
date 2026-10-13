import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "mcp"))

from project_roots import csharp_root


def write(path: Path, text: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def bar_source(repo: Path) -> Path:
    write(repo / "Bar" / "Bar.csproj")
    return write(repo / "Bar" / "Program.cs")


def test_solution_listing_the_project_is_the_root(tmp_path: Path) -> None:
    source = bar_source(tmp_path)
    write(
        tmp_path / "all" / "All.sln",
        'Project("{X}") = "Bar", "..\\Bar\\Bar.csproj", "{Y}"',
    )
    assert csharp_root(source, tmp_path) == tmp_path / "all"


def test_solution_listing_a_longer_project_name_is_not_the_root(tmp_path: Path) -> None:
    source = bar_source(tmp_path)
    write(tmp_path / "all" / "All.slnx", '<Project Path="../FooBar/FooBar.csproj" />')
    assert csharp_root(source, tmp_path) == tmp_path / "Bar"
