from collections.abc import Iterator
from pathlib import Path


def project_folders(cwd: Path) -> Iterator[Path]:
    for folder in (cwd, *cwd.parents):
        yield folder
        if (folder / ".git").exists():
            return


def config_folders(cwd: Path, project_subfolder: Path, user_folder: Path) -> list[Path]:
    in_projects = (folder / project_subfolder for folder in project_folders(cwd))
    return [*(folder for folder in in_projects if folder.is_dir()), user_folder]
