import fnmatch
import os
import re
import subprocess
from typing import NamedTuple

from text_positions import to_uri

SKIPPED_DIRECTORIES = {"bin", "obj", "node_modules"}
CREATED, CHANGED, DELETED = 1, 2, 3


def files_under(root):
    for directory, subdirectories, files in os.walk(root):
        subdirectories[:] = [
            name
            for name in subdirectories
            if not name.startswith(".") and name not in SKIPPED_DIRECTORIES
        ]
        for name in files:
            yield os.path.join(directory, name)


def unignored_files_under(root):
    try:
        output = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z"]
            + ["--cached", "--others", "--exclude-standard"],
            capture_output=True,
            check=True,
        ).stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        return files_under(root)
    return [
        os.path.join(root, os.fsdecode(name)) for name in output.split(b"\0") if name
    ]


class FileChanges(NamedTuple):
    events: list
    config_changed: bool


class ProjectFileChanges:
    def __init__(self, root, source_suffixes, config_files):
        self.root = root
        self.source_suffixes = tuple(source_suffixes)
        self.config_file = re.compile("|".join(map(fnmatch.translate, config_files)))
        self.stamps = self.current_stamps()

    def is_config(self, path):
        return self.config_file.match(os.path.basename(path)) is not None

    def is_watched(self, path):
        return path.endswith(self.source_suffixes) or self.is_config(path)

    def current_stamps(self):
        stamps = {}
        for path in unignored_files_under(self.root):
            if not self.is_watched(path):
                continue
            try:
                stat = os.stat(path)
            except OSError:
                continue
            stamps[path] = (stat.st_mtime_ns, stat.st_size)
        return stamps

    def since_last_check(self):
        previous = self.stamps
        current = self.stamps = self.current_stamps()
        created = [(path, CREATED) for path in current.keys() - previous.keys()]
        deleted = [(path, DELETED) for path in previous.keys() - current.keys()]
        changed = [
            (path, CHANGED)
            for path in current.keys() & previous.keys()
            if current[path] != previous[path]
        ]
        changes = created + deleted + changed
        return FileChanges(
            events=[{"uri": to_uri(path), "type": change} for path, change in changes],
            config_changed=any(self.is_config(path) for path, _ in changes),
        )
