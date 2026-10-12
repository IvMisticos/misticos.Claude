import fnmatch
import os
import re
import subprocess
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import NamedTuple

from lsp_types import FileEvent
from text_positions import to_uri

SKIPPED_DIRECTORIES = {"bin", "obj", "node_modules"}
CREATED, CHANGED, DELETED = 1, 2, 3

FileStamp = tuple[int, int]


def is_skipped_directory(name: str) -> bool:
    return name.startswith(".") or name in SKIPPED_DIRECTORIES


def files_under(root: str | os.PathLike[str]) -> Iterator[str]:
    for directory, subdirectories, files in os.walk(root):
        subdirectories[:] = [
            name for name in subdirectories if not is_skipped_directory(name)
        ]
        for name in files:
            yield os.path.join(directory, name)


class ProjectFiles(NamedTuple):
    unignored: list[str]
    ignored: list[str]


def project_files_under(root: Path) -> ProjectFiles:
    try:
        unignored = git_listed(root, "--cached", "--others", "--exclude-standard")
        ignored_entries = git_listed(
            root, "--others", "--ignored", "--exclude-standard", "--directory"
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ProjectFiles(unignored=list(files_under(root)), ignored=[])
    ignored = [path for entry in ignored_entries for path in ignored_files(root, entry)]
    return ProjectFiles(unignored, ignored)


def git_listed(root: Path, *options: str) -> list[str]:
    output = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z", *options],
        capture_output=True,
        check=True,
    ).stdout
    return [
        os.path.join(root, os.fsdecode(name)) for name in output.split(b"\0") if name
    ]


def ignored_files(root: Path, entry: str) -> Iterable[str]:
    directory = os.path.dirname(entry)
    if inside_skipped_directory(root, directory) or is_virtualenv(directory):
        return []
    if entry.endswith("/"):
        return files_under(directory)
    return [entry]


def inside_skipped_directory(root: Path, directory: str) -> bool:
    relative_parts = os.path.relpath(directory, root).split(os.sep)
    return any(
        is_skipped_directory(part) for part in relative_parts if part != os.curdir
    )


def is_virtualenv(directory: str) -> bool:
    return os.path.exists(os.path.join(directory, "pyvenv.cfg"))


def file_stamps(paths: Iterable[str]) -> dict[str, FileStamp]:
    stamps: dict[str, FileStamp] = {}
    for path in paths:
        try:
            stat = os.stat(path)
        except OSError:
            continue
        stamps[path] = (stat.st_mtime_ns, stat.st_size)
    return stamps


def change_between(
    previous_stamp: FileStamp | None, current_stamp: FileStamp | None
) -> int | None:
    if previous_stamp == current_stamp:
        return None
    if previous_stamp is None:
        return CREATED
    if current_stamp is None:
        return DELETED
    return CHANGED


class ProjectFileChanges:
    def __init__(
        self,
        repo: Path,
        server_root: Path,
        source_suffixes: Iterable[str],
        config_files: Iterable[str],
    ) -> None:
        self.repo = repo
        self.server_root = str(server_root)
        self.server_root_ancestors = {
            str(directory)
            for directory in server_root.parents
            if directory == repo or repo in directory.parents
        }
        self.source_suffixes = tuple(source_suffixes)
        self.config_file = re.compile("|".join(map(fnmatch.translate, config_files)))
        self.stamps = self.current_stamps()

    def is_source(self, path: str) -> bool:
        return path.endswith(self.source_suffixes)

    def is_config(self, path: str) -> bool:
        return self.config_file.match(os.path.basename(path)) is not None

    def configures_server_root(self, path: str) -> bool:
        if not self.is_config(path):
            return False
        return (
            path.startswith(self.server_root + os.sep)
            or os.path.dirname(path) in self.server_root_ancestors
        )

    def current_stamps(self) -> dict[str, FileStamp]:
        files = project_files_under(self.repo)
        return file_stamps(
            [
                *(
                    path
                    for path in files.unignored
                    if self.is_source(path) or self.is_config(path)
                ),
                *(path for path in files.ignored if self.is_source(path)),
            ]
        )

    def since_last_check(self) -> tuple[list[FileEvent], bool]:
        previous = self.stamps
        current = self.stamps = self.current_stamps()
        changes = [
            (path, change)
            for path in current.keys() | previous.keys()
            if (change := change_between(previous.get(path), current.get(path)))
        ]
        events: list[FileEvent] = [
            {"uri": to_uri(path), "type": change} for path, change in changes
        ]
        config_changed = any(self.configures_server_root(path) for path, _ in changes)
        return events, config_changed
