import re
import subprocess
from collections.abc import Collection
from pathlib import Path, PureWindowsPath

from language_servers import PROJECT_SUFFIXES, SOLUTION_SUFFIXES
from project_files import files_under


def git_root(path: Path) -> Path:
    try:
        output = subprocess.run(
            ["git", "-C", str(path.parent), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        return Path(output)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return directory_outside_git(path)


def directory_outside_git(path: Path) -> Path:
    working_directory = Path.cwd()
    if working_directory in path.parents:
        return working_directory
    return path.parent


def file_with_suffix(directory: Path, suffixes: Collection[str]) -> Path | None:
    try:
        return next(
            (child for child in directory.iterdir() if child.suffix in suffixes), None
        )
    except OSError:
        return None


def directories_up_to(path: Path, repo: Path) -> list[Path]:
    parents = list(path.parents)
    if repo not in parents:
        return []
    return parents[: parents.index(repo) + 1]


def nearest_file_with(path: Path, suffixes: Collection[str], repo: Path) -> Path | None:
    matches = (
        file_with_suffix(directory, suffixes)
        for directory in directories_up_to(path, repo)
    )
    return next((match for match in matches if match is not None), None)


QUOTED = re.compile(r'"([^"]+)"')


def quoted_file_names(text: str) -> set[str]:
    return {PureWindowsPath(quoted).name for quoted in QUOTED.findall(text)}


def solution_mentioning(project_file: Path, repo: Path) -> Path | None:
    for solution in map(Path, files_under(repo)):
        if solution.suffix not in SOLUTION_SUFFIXES:
            continue
        try:
            text = solution.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if project_file.name in quoted_file_names(text):
            return solution.parent
    return None


def csharp_root(path: Path, repo: Path) -> Path:
    nearest_solution = nearest_file_with(path, SOLUTION_SUFFIXES, repo)
    if nearest_solution is not None:
        return nearest_solution.parent
    project_file = nearest_file_with(path, PROJECT_SUFFIXES, repo)
    if project_file is None:
        return repo
    return solution_mentioning(project_file, repo) or project_file.parent


def project_root(name: str, path: Path, repo: Path) -> Path:
    if name != "csharp":
        return repo
    return csharp_root(path, repo)
