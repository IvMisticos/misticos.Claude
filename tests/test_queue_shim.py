import os
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import (
    SHIMS,
    FakeBin,
    ShimRun,
    ShimRunner,
    WrappedShimRunner,
    real_uv_directories,
    without_session_variables,
)

PRINT_ENVIRONMENT = """#!/usr/bin/env bash
echo "PATH=$PATH"
echo "VIRTUAL_ENV=${VIRTUAL_ENV-}"
"""

UV_WITHOUT_PYTHON = f"""#!/usr/bin/env bash
here=$(dirname "$0")
case " $* " in
  *" python install "*)
    echo "$PWD" > "$here/uv-install-directory"
    ;;
  *" python find "*)
    [ -e "$here/uv-install-directory" ] || exit 2
    echo {sys.executable}
    ;;
esac
"""


@pytest.fixture
def run_cargo(shim_runner: ShimRunner) -> ShimRun:
    return shim_runner("cargo", PRINT_ENVIRONMENT)


@pytest.fixture
def inside_project_with_venv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = tmp_path / "project"
    project.mkdir()
    subprocess.run(
        [sys.executable, "-m", "venv", "--without-pip", project / ".venv"], check=True
    )
    monkeypatch.chdir(project)


@pytest.mark.usefixtures("inside_project_with_venv")
def test_tool_sees_the_callers_environment(run_cargo: ShimRun) -> None:
    result = run_cargo("--version")

    assert result.returncode == 0, result.stderr
    seen = dict(line.split("=", 1) for line in result.stdout.splitlines())
    assert seen["PATH"].split(os.pathsep)[0] == str(SHIMS)
    assert seen["VIRTUAL_ENV"] == os.environ.get("VIRTUAL_ENV", "")


def test_reaches_cargo_past_a_wrapper_that_runs_the_shim(
    wrapped_shim_runner: WrappedShimRunner,
) -> None:
    run = wrapped_shim_runner("cargo", '#!/usr/bin/env bash\necho "ran $*"\n', "")
    assert run("--version").stdout == "ran --version\n"


@pytest.fixture
def inside_project_with_broken_uv_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "uv.toml").write_text("this is not toml [\n")
    monkeypatch.chdir(project)


@pytest.mark.usefixtures("inside_project_with_broken_uv_config")
def test_missing_python_installs_outside_the_project(
    run_cargo: ShimRun, fake_bin: FakeBin
) -> None:
    bin_dir = fake_bin("uv", UV_WITHOUT_PYTHON)

    result = run_cargo("--version")

    assert result.returncode == 0, result.stderr
    assert (bin_dir / "uv-install-directory").read_text() == "/\n"


@pytest.fixture
def environment_with_only_local_uv(home: Path) -> dict[str, str]:
    local_bin = home / ".local" / "bin"
    local_bin.mkdir(parents=True)
    (local_bin / "uv").symlink_to(Path(real_uv_directories()[0]) / "uv")
    environment = without_session_variables(os.environ)
    environment.update(
        HOME=str(home), PATH=os.pathsep.join([str(SHIMS), "/usr/bin", "/bin"])
    )
    return environment


def run_shim(
    name: str, environment: dict[str, str], *arguments: str
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [SHIMS / name, *arguments],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def test_runs_uv_when_it_is_only_in_the_local_bin(
    environment_with_only_local_uv: dict[str, str],
) -> None:
    result = run_shim("uv", environment_with_only_local_uv, "--version")

    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("uv ")


def test_runs_a_missing_tool_through_mise(
    environment_with_only_local_uv: dict[str, str], fake_bin: FakeBin
) -> None:
    mise_dir = fake_bin("mise", '#!/usr/bin/env bash\necho "mise $*"\n')
    environment = environment_with_only_local_uv
    environment["PATH"] += os.pathsep + str(mise_dir)

    result = run_shim("bun", environment, "--version")

    assert result.returncode == 0, result.stderr
    assert result.stdout == "mise --quiet x bun -- bun --version\n"


MISE_WITH_UV_AND_PYTHON = f"""#!/usr/bin/env bash
case " $* " in
  *" python find "*) echo {sys.executable} ;;
  *) echo "mise $*" ;;
esac
"""


def test_runs_uv_through_mise_when_uv_is_missing(home: Path, fake_bin: FakeBin) -> None:
    mise_dir = fake_bin("mise", MISE_WITH_UV_AND_PYTHON)
    environment = without_session_variables(os.environ)
    environment.update(
        HOME=str(home),
        PATH=os.pathsep.join([str(SHIMS), str(mise_dir), "/usr/bin", "/bin"]),
    )

    result = run_shim("uv", environment, "--version")

    assert result.returncode == 0, result.stderr
    assert result.stdout == "mise --quiet x uv -- uv --version\n"


MISE_RUNNING_FROM_PATH = """#!/usr/bin/env bash
[ "$1 $2" = "--quiet x" ] || exit 2
shift 4
exec "$@"
"""


def test_mise_does_not_reenter_the_shim_for_a_tool_it_lacks(
    environment_with_only_local_uv: dict[str, str], fake_bin: FakeBin
) -> None:
    mise_dir = fake_bin("mise", MISE_RUNNING_FROM_PATH)
    environment = environment_with_only_local_uv
    environment["PATH"] += os.pathsep + str(mise_dir)

    result = subprocess.run(
        [SHIMS / "cargo", "build"],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == 127


def test_queues_a_build_that_mise_runs(
    environment_with_only_local_uv: dict[str, str], fake_bin: FakeBin
) -> None:
    mise_dir = fake_bin(
        "mise", '#!/usr/bin/env bash\necho "held=${HARNESS_QUEUE_HELD-} $*"\n'
    )
    environment = environment_with_only_local_uv
    environment["PATH"] += os.pathsep + str(mise_dir)

    result = run_shim("dotnet", environment, "build")

    assert result.returncode == 0, result.stderr
    assert result.stdout == "held=1 --quiet x dotnet -- dotnet build\n"


def test_reports_a_tool_that_mise_cannot_run_either(
    environment_with_only_local_uv: dict[str, str],
) -> None:
    result = run_shim("bun", environment_with_only_local_uv, "--version")

    assert result.returncode == 127
    assert result.stderr == "queue: bun is not installed\n"


def test_runs_a_tool_from_the_mise_shims(
    environment_with_only_local_uv: dict[str, str], home: Path
) -> None:
    mise_shims = home / ".local" / "share" / "mise" / "shims"
    mise_shims.mkdir(parents=True)
    bun = mise_shims / "bun"
    bun.write_text('#!/usr/bin/env bash\necho "bun $*"\n')
    bun.chmod(0o755)

    result = run_shim("bun", environment_with_only_local_uv, "--version")

    assert result.returncode == 0, result.stderr
    assert result.stdout == "bun --version\n"


FAIL_ON_SECOND_RUN = 'echo run >> "$0"; [ "$(wc -l < "$0")" -lt 2 ]'


def queue_bench(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [SHIMS / "queue", "bench", *arguments],
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture
def run_log(tmp_path: Path) -> Path:
    return tmp_path / "runs"


def test_bench_runs_once_by_default(run_log: Path) -> None:
    result = queue_bench("--", "bash", "-c", 'echo run >> "$0"', str(run_log))

    assert result.returncode == 0, result.stderr
    assert run_log.read_text().splitlines() == ["run"]


def test_bench_repeats_the_command(run_log: Path) -> None:
    result = queue_bench(
        "--runs", "3", "--", "bash", "-c", 'echo run >> "$0"', str(run_log)
    )

    assert result.returncode == 0, result.stderr
    assert run_log.read_text().splitlines() == ["run"] * 3


def test_bench_stops_at_the_first_failing_run(run_log: Path) -> None:
    result = queue_bench(
        "--runs", "5", "--", "bash", "-c", FAIL_ON_SECOND_RUN, str(run_log)
    )

    assert result.returncode == 1
    assert run_log.read_text().splitlines() == ["run"] * 2


def test_bench_rejects_zero_runs() -> None:
    result = queue_bench("--runs", "0", "--", "true")

    assert result.returncode == 2
    assert "needs at least 1" in result.stderr


MISE_SHIM_FALLING_THROUGH = """#!/usr/bin/env bash
calls="$HOME/mise-shim-calls"
echo call >> "$calls"
[ "$(wc -l < "$calls")" -le 20 ] || exit 99
own_dir=$(cd "$(dirname "$0")" && pwd)
IFS=: read -ra dirs <<< "$PATH"
for dir in "${dirs[@]}"; do
  [ "$dir" != "$own_dir" ] && [ -x "$dir/uv" ] && exec "$dir/uv" "$@"
done
exit 127
"""


@pytest.fixture
def mise_uv_shim(home: Path) -> Path:
    mise_shims = home / ".local" / "share" / "mise" / "shims"
    mise_shims.mkdir(parents=True)
    shim = mise_shims / "uv"
    shim.write_text(MISE_SHIM_FALLING_THROUGH)
    shim.chmod(0o755)
    return mise_shims


def mise_shim_calls(home: Path) -> int:
    calls = home / "mise-shim-calls"
    return len(calls.read_text().splitlines()) if calls.exists() else 0


def test_queue_never_runs_its_uv_through_a_mise_shim(
    home: Path, mise_uv_shim: Path
) -> None:
    environment = without_session_variables(os.environ)
    environment.update(
        HOME=str(home),
        PATH=os.pathsep.join([str(SHIMS), str(mise_uv_shim), "/usr/bin", "/bin"]),
    )

    result = subprocess.run(
        [SHIMS / "uv", "--version"],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )

    assert mise_shim_calls(home) == 0
    assert result.returncode == 127
    assert result.stderr == "queue: uv is not installed\n"


def test_mise_shim_falling_through_to_the_plugin_shim_stops(
    environment_with_only_local_uv: dict[str, str], home: Path, mise_uv_shim: Path
) -> None:
    environment = environment_with_only_local_uv
    environment["PATH"] = os.pathsep.join(
        [str(SHIMS), str(mise_uv_shim), "/usr/bin", "/bin"]
    )

    result = subprocess.run(
        [SHIMS / "uv", "--version"],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("uv ")
    assert mise_shim_calls(home) == 1
