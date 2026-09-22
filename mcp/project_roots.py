import os
import subprocess
from pathlib import Path

SOLUTION_SUFFIXES = (".sln", ".slnx", ".slnf")
PROJECT_SUFFIXES = (".csproj",)
SKIPPED_DIRECTORIES = {"bin", "obj", "node_modules"}


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


def holds_file_with(directory, suffixes):
    try:
        return any(child.suffix in suffixes for child in directory.iterdir())
    except OSError:
        return False


def nearest_directory_with(path, suffixes, repo):
    if repo not in path.parents:
        return None
    for directory in path.parents:
        if holds_file_with(directory, suffixes):
            return directory
        if directory == repo:
            return None
    return None


def solution_files_under(repo):
    found = []
    for directory, subdirectories, files in os.walk(repo):
        subdirectories[:] = [
            name
            for name in subdirectories
            if not name.startswith(".") and name not in SKIPPED_DIRECTORIES
        ]
        found.extend(
            Path(directory) / name
            for name in files
            if Path(name).suffix in SOLUTION_SUFFIXES
        )
    return found


def solution_mentioning(project_file, repo):
    for solution in solution_files_under(repo):
        try:
            if project_file.name in solution.read_text(
                encoding="utf-8", errors="replace"
            ):
                return solution.parent
        except OSError:
            continue
    return None


def nearest_project_file(path, repo):
    directory = nearest_directory_with(path, PROJECT_SUFFIXES, repo)
    if directory is None:
        return None
    return next(
        child for child in directory.iterdir() if child.suffix in PROJECT_SUFFIXES
    )


def csharp_root(path, repo):
    nearest_solution = nearest_directory_with(path, SOLUTION_SUFFIXES, repo)
    if nearest_solution is not None:
        return nearest_solution
    project_file = nearest_project_file(path, repo)
    if project_file is None:
        return repo
    return solution_mentioning(project_file, repo) or project_file.parent


def project_root(name, path):
    repo = git_root(path)
    if name != "csharp":
        return repo
    return csharp_root(path, repo)
