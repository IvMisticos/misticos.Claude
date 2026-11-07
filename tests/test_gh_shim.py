import subprocess
import sys

import pytest
from conftest import FAKE_GH, FakeBin, ShimRun, ShimRunner, run_shim
from pull_request_writes import denial

WRITES_ON_EVERY_PATH = [
    ["pr", "merge", "1"],
    ["api", "-X", "POST", "repos/o/r/pulls/1/reviews"],
    ["api", "repos/o/r/pulls/1/comments", "--input", "-"],
]
FAKE_GH_ECHOING_INPUT = """#!/usr/bin/env bash
echo "ran $* with $(cat)"
"""


@pytest.fixture
def run_gh_in_cloud(shim_runner: ShimRunner) -> ShimRun:
    return shim_runner("gh", FAKE_GH, CLAUDE_CODE_REMOTE="true")


@pytest.fixture
def run_gh_elsewhere(shim_runner: ShimRunner) -> ShimRun:
    return shim_runner("gh", FAKE_GH)


def assert_ran(result: subprocess.CompletedProcess[str], arguments: list[str]) -> None:
    assert result.returncode == 0, result.stderr
    assert result.stdout == f"ran {' '.join(arguments)}\n"


@pytest.mark.parametrize("arguments", WRITES_ON_EVERY_PATH)
def test_denies_pull_request_writes_in_claude_cloud(
    run_gh_in_cloud: ShimRun, arguments: list[str]
) -> None:
    result = run_gh_in_cloud(*arguments)
    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr == f"{denial(arguments)}\n"


@pytest.mark.parametrize(
    "arguments",
    [
        ["pr", "view", "1"],
        ["pr", "create", "--help"],
        ["pr", "comment", "1", "--attach", "shot.png"],
        ["api", "repos/o/r/issues", "-f", "title=x"],
        [],
    ],
)
def test_runs_other_commands(run_gh_in_cloud: ShimRun, arguments: list[str]) -> None:
    assert_ran(run_gh_in_cloud(*arguments), arguments)


def test_passes_standard_input_to_gh(shim_runner: ShimRunner) -> None:
    run = shim_runner("gh", FAKE_GH_ECHOING_INPUT, CLAUDE_CODE_REMOTE="true")
    result = run("api", "repos/o/r/issues", "--input", "-", standard_input="body")
    assert result.returncode == 0, result.stderr
    assert result.stdout == "ran api repos/o/r/issues --input - with body\n"


@pytest.mark.parametrize("arguments", WRITES_ON_EVERY_PATH)
def test_runs_pull_request_writes_on_request(
    run_gh_in_cloud: ShimRun, arguments: list[str]
) -> None:
    assert_ran(run_gh_in_cloud(*arguments, ALLOW_GH_PULL_REQUEST_WRITE="1"), arguments)


@pytest.mark.parametrize("arguments", WRITES_ON_EVERY_PATH)
def test_runs_pull_request_writes_outside_claude_cloud(
    run_gh_elsewhere: ShimRun, arguments: list[str]
) -> None:
    assert_ran(run_gh_elsewhere(*arguments), arguments)


def test_runs_pull_request_writes_when_the_session_is_not_remote(
    run_gh_elsewhere: ShimRun,
) -> None:
    result = run_gh_elsewhere("pr", "merge", "1", CLAUDE_CODE_REMOTE="false")
    assert_ran(result, ["pr", "merge", "1"])


def test_runs_gh_without_home(fake_bin: FakeBin) -> None:
    environment = {"PATH": f"{fake_bin('gh', FAKE_GH)}:/usr/bin:/bin"}
    assert_ran(run_shim("gh", environment, "--version"), ["--version"])


def test_checks_with_the_python_the_session_found(fake_bin: FakeBin) -> None:
    fake_bin("uv", "#!/usr/bin/env bash\nexit 3\n")
    environment = {
        "PATH": f"{fake_bin('gh', FAKE_GH)}:/usr/bin:/bin",
        "CLAUDE_CODE_REMOTE": "true",
        "HARNESS_HOOK_PYTHON": sys.executable,
    }
    result = run_shim("gh", environment, "pr", "merge", "1")
    assert result.returncode == 1
    assert result.stderr == f"{denial(['pr', 'merge', '1'])}\n"
