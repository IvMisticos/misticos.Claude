FAKE_DOTNET = """#!/usr/bin/env bash
echo "$MSBUILDDISABLENODEREUSE $DOTNET_CLI_USE_MSBUILD_SERVER $*"
"""


def test_runs_dotnet_without_shared_build_nodes(shim_runner):
    run_dotnet = shim_runner(
        "dotnet",
        FAKE_DOTNET,
        HARNESS_QUEUE_HELD="1",
        MSBUILDDISABLENODEREUSE="0",
        DOTNET_CLI_USE_MSBUILD_SERVER="1",
    )
    assert run_dotnet("build").stdout == "1 0 build\n"
