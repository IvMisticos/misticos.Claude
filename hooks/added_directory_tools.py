#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# [tool.ty.environment]
# root = ["."]
# ///

from pathlib import Path

from hook_io import added_directory_of, read_payload
from setup_tools import (
    exit_if_any_failed,
    install_mise_tools_of_projects,
    is_cloud_session_as_root,
)


def main() -> None:
    directory = added_directory_of(read_payload())
    if directory is None or not is_cloud_session_as_root():
        return
    exit_if_any_failed(install_mise_tools_of_projects(Path(directory)))


if __name__ == "__main__":
    main()
