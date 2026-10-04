import os
import subprocess

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


def file_stamps(root, suffixes):
    stamps = {}
    for path in unignored_files_under(root):
        if not path.endswith(suffixes):
            continue
        try:
            stat = os.stat(path)
        except OSError:
            continue
        stamps[path] = (stat.st_mtime_ns, stat.st_size)
    return stamps


class ProjectFileChanges:
    def __init__(self, root, suffixes):
        self.root = root
        self.suffixes = tuple(suffixes)
        self.stamps = file_stamps(root, self.suffixes)

    def since_last_check(self):
        previous = self.stamps
        current = self.stamps = file_stamps(self.root, self.suffixes)
        created = [(path, CREATED) for path in current.keys() - previous.keys()]
        deleted = [(path, DELETED) for path in previous.keys() - current.keys()]
        changed = [
            (path, CHANGED)
            for path in current.keys() & previous.keys()
            if current[path] != previous[path]
        ]
        return [
            {"uri": to_uri(path), "type": change}
            for path, change in created + deleted + changed
        ]
