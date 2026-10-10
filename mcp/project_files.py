import fnmatch
import os
import re
import subprocess
from typing import NamedTuple

from text_positions import to_uri

SKIPPED_DIRECTORIES = {"bin", "obj", "node_modules"}
CREATED, CHANGED, DELETED = 1, 2, 3


def is_skipped_directory(name):
    return name.startswith(".") or name in SKIPPED_DIRECTORIES


def files_under(root):
    for directory, subdirectories, files in os.walk(root):
        subdirectories[:] = [
            name for name in subdirectories if not is_skipped_directory(name)
        ]
        for name in files:
            yield os.path.join(directory, name)


class ProjectFiles(NamedTuple):
    unignored: list
    ignored: list


def project_files_under(root):
    try:
        unignored = git_listed(root, "--cached", "--others", "--exclude-standard")
        ignored_entries = git_listed(
            root, "--others", "--ignored", "--exclude-standard", "--directory"
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ProjectFiles(unignored=list(files_under(root)), ignored=[])
    ignored = [path for entry in ignored_entries for path in ignored_files(root, entry)]
    return ProjectFiles(unignored, ignored)


def git_listed(root, *options):
    output = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z", *options],
        capture_output=True,
        check=True,
    ).stdout
    return [
        os.path.join(root, os.fsdecode(name)) for name in output.split(b"\0") if name
    ]


def ignored_files(root, entry):
    directory = os.path.dirname(entry)
    if inside_skipped_directory(root, directory) or is_virtualenv(directory):
        return []
    if entry.endswith("/"):
        return files_under(directory)
    return [entry]


def inside_skipped_directory(root, directory):
    relative_parts = os.path.relpath(directory, root).split(os.sep)
    return any(
        is_skipped_directory(part) for part in relative_parts if part != os.curdir
    )


def is_virtualenv(directory):
    return os.path.exists(os.path.join(directory, "pyvenv.cfg"))


def file_stamps(paths):
    stamps = {}
    for path in paths:
        try:
            stat = os.stat(path)
        except OSError:
            continue
        stamps[path] = (stat.st_mtime_ns, stat.st_size)
    return stamps


def change_between(previous_stamp, current_stamp):
    if previous_stamp == current_stamp:
        return None
    if previous_stamp is None:
        return CREATED
    if current_stamp is None:
        return DELETED
    return CHANGED


class ProjectFileChanges:
    def __init__(self, repo, server_root, source_suffixes, config_files):
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

    def is_source(self, path):
        return path.endswith(self.source_suffixes)

    def is_config(self, path):
        return self.config_file.match(os.path.basename(path)) is not None

    def configures_server_root(self, path):
        if not self.is_config(path):
            return False
        return (
            path.startswith(self.server_root + os.sep)
            or os.path.dirname(path) in self.server_root_ancestors
        )

    def current_stamps(self):
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

    def since_last_check(self):
        previous = self.stamps
        current = self.stamps = self.current_stamps()
        changes = [
            (path, change)
            for path in current.keys() | previous.keys()
            if (change := change_between(previous.get(path), current.get(path)))
        ]
        events = [{"uri": to_uri(path), "type": change} for path, change in changes]
        config_changed = any(self.configures_server_root(path) for path, _ in changes)
        return events, config_changed
