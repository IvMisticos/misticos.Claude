#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///

import os
import shlex
from pathlib import Path

HOOKS_DIR = Path(__file__).resolve().parent
SHIMS_DIR = HOOKS_DIR.parent / "shims"
SESSION_ENVIRONMENT_SCRIPT = HOOKS_DIR / "session_environment.sh"


def project_dir():
    return os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()


def session_environment_command():
    script = str(SESSION_ENVIRONMENT_SCRIPT)
    return shlex.join([".", script, str(SHIMS_DIR), project_dir()])


def main():
    env_file = os.environ.get("CLAUDE_ENV_FILE")
    if os.name != "posix" or not env_file:
        return
    env_path = Path(env_file)
    written = env_path.read_text() if env_path.exists() else ""
    line = session_environment_command() + "\n"
    if line not in written:
        with env_path.open("a") as env:
            env.write(line)


if __name__ == "__main__":
    main()
