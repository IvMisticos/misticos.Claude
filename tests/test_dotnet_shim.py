import os
import subprocess

from test_git_shim import SHIMS, without_session_variables

FAKE_DOTNET = """#!/usr/bin/env bash
echo "$MSBUILDDISABLENODEREUSE $DOTNET_CLI_USE_MSBUILD_SERVER $*"
"""


def test_runs_dotnet_without_shared_build_nodes(tmp_path):
    real_bin = tmp_path / "bin"
    real_bin.mkdir()
    fake_dotnet = real_bin / "dotnet"
    fake_dotnet.write_text(FAKE_DOTNET)
    fake_dotnet.chmod(0o755)
    environment = without_session_variables(os.environ)
    environment["PATH"] = f"{SHIMS}:{real_bin}:/usr/bin:/bin"
    environment["HARNESS_QUEUE_HELD"] = "1"
    result = subprocess.run(
        [SHIMS / "dotnet", "build"],
        env=environment,
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout == "1 0 build\n"
