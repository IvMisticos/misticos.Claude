#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///

import os
import shlex
from pathlib import Path

BIN_DIR = Path(__file__).resolve().parent.parent / "bin"
PATH_EXPORT = f'export PATH={shlex.quote(str(BIN_DIR))}:"$PATH"\n'


def main():
    env_file = os.environ.get("CLAUDE_ENV_FILE")
    if os.name != "posix" or not env_file:
        return
    env_path = Path(env_file)
    if env_path.exists() and PATH_EXPORT in env_path.read_text():
        return
    with env_path.open("a") as env:
        env.write(PATH_EXPORT)


if __name__ == "__main__":
    main()
