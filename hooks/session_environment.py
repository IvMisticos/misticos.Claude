#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///

import os
import shlex
from pathlib import Path

SHIMS_DIR = Path(__file__).resolve().parent.parent / "shims"
IDENTITY_VARIABLES = (
    "GIT_AUTHOR_NAME",
    "GIT_AUTHOR_EMAIL",
    "GIT_COMMITTER_NAME",
    "GIT_COMMITTER_EMAIL",
)


def harness_git_identity():
    return "|".join(os.environ.get(name, "") for name in IDENTITY_VARIABLES)


def session_exports():
    return [
        f'export PATH={shlex.quote(str(SHIMS_DIR))}:"$PATH"\n',
        f"export MISTICOS_HARNESS_GIT_IDENTITY={shlex.quote(harness_git_identity())}\n",
    ]


def main():
    env_file = os.environ.get("CLAUDE_ENV_FILE")
    if os.name != "posix" or not env_file:
        return
    env_path = Path(env_file)
    written = env_path.read_text() if env_path.exists() else ""
    missing = [line for line in session_exports() if line not in written]
    with env_path.open("a") as env:
        env.writelines(missing)


if __name__ == "__main__":
    main()
