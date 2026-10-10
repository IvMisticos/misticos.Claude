import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SHIMS = ROOT / "shims"
FAKE_GH = """#!/usr/bin/env bash
echo "ran $*"
"""


def without_session_variables(environment):
    return {
        name: value
        for name, value in environment.items()
        if not name.startswith(("GIT_", "HARNESS_", "CLAUDE_", "ALLOW_"))
    }


@pytest.fixture
def fake_bin(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    def add(name, script):
        program = bin_dir / name
        program.write_text(script)
        program.chmod(0o755)
        return bin_dir

    return add


@pytest.fixture
def shim_runner(fake_bin):
    def runner(name, fake_script, **base_environment):
        environment = without_session_variables(os.environ)
        environment["PATH"] = f"{SHIMS}:{fake_bin(name, fake_script)}:/usr/bin:/bin"
        environment.update(base_environment)

        def run(*arguments, **extra_environment):
            return subprocess.run(
                [SHIMS / name, *arguments],
                env={**environment, **extra_environment},
                capture_output=True,
                text=True,
                check=False,
            )

        return run

    return runner
