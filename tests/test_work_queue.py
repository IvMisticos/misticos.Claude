import signal
from pathlib import Path

import pytest
from work_queue import HeldRunner, StartingChild, parse_bench_arguments, run_repeatedly

RECORD_RUN = 'echo run >> "$0"'
FAIL_ON_SECOND_RUN = f'{RECORD_RUN}; [ "$(wc -l < "$0")" -lt 2 ]'


@pytest.fixture
def run_log(tmp_path: Path) -> Path:
    return tmp_path / "runs"


def recorded_runs(run_log: Path) -> list[str]:
    return run_log.read_text().splitlines()


def test_bench_runs_once_by_default() -> None:
    arguments = parse_bench_arguments(["bench", "--", "true"])

    assert arguments.runs == 1
    assert arguments.command == ["true"]


def test_bench_reads_the_number_of_runs() -> None:
    assert parse_bench_arguments(["bench", "--runs", "3", "--", "true"]).runs == 3


def test_bench_rejects_zero_runs(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        parse_bench_arguments(["bench", "--runs", "0", "--", "true"])

    assert exit_info.value.code == 2
    assert "needs at least 1" in capsys.readouterr().err


def test_repeats_the_command(run_log: Path) -> None:
    status = run_repeatedly(["bash", "-c", RECORD_RUN, str(run_log)], 3, HeldRunner())

    assert status == 0
    assert recorded_runs(run_log) == ["run"] * 3


def test_stops_at_the_first_failing_run(run_log: Path) -> None:
    command = ["bash", "-c", FAIL_ON_SECOND_RUN, str(run_log)]

    status = run_repeatedly(command, 5, HeldRunner())

    assert status == 1
    assert recorded_runs(run_log) == ["run"] * 2


def test_exits_on_a_stop_signal_while_no_child_runs() -> None:
    with pytest.raises(SystemExit) as exit_info:
        HeldRunner().handle_stop_signal(signal.SIGTERM, None)

    assert exit_info.value.code == 128 + signal.SIGTERM


def test_holds_a_stop_signal_until_the_child_has_started() -> None:
    runner = HeldRunner()
    starting = StartingChild()
    runner.state = starting

    runner.handle_stop_signal(signal.SIGTERM, None)

    assert starting.pending_signal == signal.SIGTERM
