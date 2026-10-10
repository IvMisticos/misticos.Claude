import subprocess
from pathlib import Path

from project_files import files_under

SOLUTION_SUFFIXES = (".sln", ".slnx", ".slnf")
PROJECT_SUFFIXES = (".csproj",)


def git_root(path):
    try:
        output = subprocess.run(
            ["git", "-C", str(path.parent), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        return Path(output)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return Path.cwd()


def file_with_suffix(directory, suffixes):
    try:
        return next(
            (child for child in directory.iterdir() if child.suffix in suffixes), None
        )
    except OSError:
        return None


def nearest_file_with(path, suffixes, repo):
    if repo not in path.parents:
        return None
    for directory in path.parents:
        match = file_with_suffix(directory, suffixes)
        if match is not None:
            return match
        if directory == repo:
            return None
    return None


def solution_mentioning(project_file, repo):
    for solution in map(Path, files_under(repo)):
        if solution.suffix not in SOLUTION_SUFFIXES:
            continue
        try:
            if project_file.name in solution.read_text(
                encoding="utf-8", errors="replace"
            ):
                return solution.parent
        except OSError:
            continue
    return None


def csharp_root(path, repo):
    nearest_solution = nearest_file_with(path, SOLUTION_SUFFIXES, repo)
    if nearest_solution is not None:
        return nearest_solution.parent
    project_file = nearest_file_with(path, PROJECT_SUFFIXES, repo)
    if project_file is None:
        return repo
    return solution_mentioning(project_file, repo) or project_file.parent


def project_root(name, path, repo):
    if name != "csharp":
        return repo
    return csharp_root(path, repo)
