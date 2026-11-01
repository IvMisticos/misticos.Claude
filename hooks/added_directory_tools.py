#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# [tool.ty.environment]
# root = ["."]
# ///

import sys
from pathlib import Path

from hook_io import absolute_path_at, read_payload
from install_lock import install_lock
from setup_tools import (
    exit_if_any_failed,
    install_mise_tools_of_projects,
    is_cloud_session_as_root,
    mise_is_installed,
)


def install_mise_tools_of(directory: Path) -> list[str]:
    with install_lock():
        if not mise_is_installed():
            sys.exit(f"mise is not installed, so {directory} got none of its tools")
        return install_mise_tools_of_projects(directory)


def main() -> None:
    directory = absolute_path_at(read_payload(), "directory")
    if directory is None or not is_cloud_session_as_root():
        return
    exit_if_any_failed(install_mise_tools_of(Path(directory)))


if __name__ == "__main__":
    main()
