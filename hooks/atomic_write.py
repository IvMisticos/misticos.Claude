import os
import tempfile
from pathlib import Path

DEFAULT_MODE = 0o644


def write_atomically(path: Path, text: str) -> None:
    mode = path.stat().st_mode & 0o777 if path.exists() else DEFAULT_MODE
    descriptor, staged = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".")
    try:
        with os.fdopen(descriptor, "w") as staged_file:
            staged_file.write(text)
        os.chmod(staged, mode)
        os.replace(staged, path)
    except BaseException:
        Path(staged).unlink(missing_ok=True)
        raise
