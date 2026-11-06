#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# [tool.ty.environment]
# root = ["."]
# ///

import argparse
import contextlib
import fcntl
import os
import signal
import subprocess
import sys
import time
from collections.abc import Generator, Sequence
from io import TextIOWrapper
from pathlib import Path
from types import FrameType
from typing import NamedTuple, NoReturn

from core_pinning import CAN_PIN_CORES, pinned, plan_cores, restore_abandoned_pinning
from queued_commands import queues

HELD_VARIABLE = "HARNESS_QUEUE_HELD"
LOCK_DIR_VARIABLE = "HARNESS_QUEUE_LOCK_DIR"
LOCK_DIR = Path(
    os.environ.get(LOCK_DIR_VARIABLE) or f"/tmp/misticos-queue-{os.getuid()}"
)
MACHINE_LOCK = LOCK_DIR / "machine.lock"
TURNSTILE_LOCK = LOCK_DIR / "turnstile.lock"
BENCHMARK_LOCK = LOCK_DIR / "benchmark.lock"
PINNING_STATE = LOCK_DIR / "pinning.json"
USABLE_CPUS = len(os.sched_getaffinity(0)) if CAN_PIN_CORES else os.cpu_count() or 1
BUILD_SLOTS = max(1, USABLE_CPUS // 2)
SLOT_POLL_SECONDS = 0.5
STOP_SIGNALS = (signal.SIGTERM, signal.SIGHUP)
SIGNALS_PYTHON_IGNORES = (signal.SIGPIPE, signal.SIGXFSZ)


def notice(message: str) -> None:
    print(f"queue: {message}", file=sys.stderr, flush=True)


def open_lock_file(path: Path) -> TextIOWrapper:
    LOCK_DIR.mkdir(mode=0o700, exist_ok=True)
    if LOCK_DIR.lstat().st_uid != os.getuid():
        sys.exit(f"queue: {LOCK_DIR} belongs to another user")
    return open(path, "a")


def lock_now(handle: TextIOWrapper, operation: int) -> bool:
    try:
        fcntl.flock(handle, operation | fcntl.LOCK_NB)
    except BlockingIOError:
        return False
    return True


def try_lock(path: Path, operation: int) -> TextIOWrapper | None:
    handle = open_lock_file(path)
    if lock_now(handle, operation):
        return handle
    handle.close()
    return None


@contextlib.contextmanager
def locked(path: Path, operation: int, waiting_message: str) -> Generator[None]:
    with open_lock_file(path) as handle:
        if not lock_now(handle, operation):
            notice(waiting_message)
            fcntl.flock(handle, operation)
        yield


@contextlib.contextmanager
def machine_locked(operation: int, waiting_message: str) -> Generator[None]:
    with open_lock_file(MACHINE_LOCK) as machine:
        with open_lock_file(TURNSTILE_LOCK) as turnstile:
            if not (
                lock_now(turnstile, fcntl.LOCK_EX) and lock_now(machine, operation)
            ):
                notice(waiting_message)
                fcntl.flock(turnstile, fcntl.LOCK_EX)
                fcntl.flock(machine, operation)
        yield


def free_build_slot() -> TextIOWrapper | None:
    for index in range(BUILD_SLOTS):
        slot = try_lock(LOCK_DIR / f"build-{index}.lock", fcntl.LOCK_EX)
        if slot:
            return slot
    return None


@contextlib.contextmanager
def build_slot() -> Generator[None]:
    slot = free_build_slot()
    if slot is None:
        notice("waiting for a build slot")
    while slot is None:
        time.sleep(SLOT_POLL_SECONDS)
        slot = free_build_slot()
    with slot:
        yield


def signal_exit_status(signal_number: int) -> int:
    return 128 + signal_number


def exit_status(returncode: int) -> int:
    return signal_exit_status(-returncode) if returncode < 0 else returncode


class HeldRunner:
    def __init__(self) -> None:
        self.received_stop_signal: int | None = None
        self.starting_child = False
        self.running_child: subprocess.Popen[bytes] | None = None

    def handle_stop_signal(self, signal_number: int, _frame: FrameType | None) -> None:
        self.received_stop_signal = signal_number
        if self.running_child:
            self.running_child.send_signal(signal_number)
        elif not self.starting_child:
            sys.exit(signal_exit_status(signal_number))

    def start(self, command: Sequence[str]) -> subprocess.Popen[bytes]:
        environment = {**os.environ, HELD_VARIABLE: "1"}
        self.starting_child = True
        try:
            child = subprocess.Popen(command, env=environment)
            self.running_child = child
        finally:
            self.starting_child = False
        if self.received_stop_signal:
            child.send_signal(self.received_stop_signal)
        return child

    def run(self, command: Sequence[str]) -> int:
        child = self.start(command)
        try:
            return exit_status(child.wait())
        finally:
            self.running_child = None


def restore_pinning_of_killed_benchmark() -> None:
    if not CAN_PIN_CORES:
        return
    benchmark = try_lock(BENCHMARK_LOCK, fcntl.LOCK_EX)
    if benchmark is None:
        return
    with benchmark:
        restore_abandoned_pinning(PINNING_STATE)


def run_build(command: Sequence[str], runner: HeldRunner) -> int:
    restore_pinning_of_killed_benchmark()
    alone_message = "waiting for a benchmark that runs alone"
    with build_slot(), machine_locked(fcntl.LOCK_SH, alone_message):
        return runner.run(command)


class ToolRun(NamedTuple):
    name: str
    command: list[str]
    arguments: list[str]


def parse_tool_run(words: Sequence[str]) -> ToolRun:
    name, command_length, *rest = words
    length = int(command_length)
    return ToolRun(name, rest[:length], rest[length:])


def exec_unqueued(command: list[str]) -> NoReturn:
    for ignored_signal in SIGNALS_PYTHON_IGNORES:
        signal.signal(ignored_signal, signal.SIG_DFL)
    os.execv(command[0], command)


def run_tool(tool: ToolRun, runner: HeldRunner) -> int:
    command = [*tool.command, *tool.arguments]
    if not queues(tool.name, tool.arguments):
        exec_unqueued(command)
    return run_build(command, runner)


def run_repeatedly(command: Sequence[str], runs: int, runner: HeldRunner) -> int:
    for _ in range(runs):
        status = runner.run(command)
        if runner.received_stop_signal:
            return signal_exit_status(runner.received_stop_signal)
        if status != 0:
            return status
    return 0


def run_benchmark(
    command: Sequence[str], cores: int, alone: bool, runs: int, runner: HeldRunner
) -> int:
    with contextlib.ExitStack() as held:
        held.enter_context(
            locked(BENCHMARK_LOCK, fcntl.LOCK_EX, "waiting for the running benchmark")
        )
        plan = None
        if CAN_PIN_CORES:
            restore_abandoned_pinning(PINNING_STATE)
            plan = plan_cores(cores, alone)
        elif not alone:
            notice("this system cannot pin cores, so the benchmark runs alone")
        if alone or plan is None:
            held.enter_context(
                machine_locked(fcntl.LOCK_EX, "waiting for builds to finish")
            )
        if plan:
            held.enter_context(pinned(plan, PINNING_STATE))
        return run_repeatedly(command, runs, runner)


def positive_count(text: str) -> int:
    count = int(text)
    if count < 1:
        raise argparse.ArgumentTypeError("needs at least 1")
    return count


def parse_bench_arguments(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="queue")
    modes = parser.add_subparsers(dest="mode", required=True)
    bench = modes.add_parser("bench")
    bench.add_argument("--cores", type=positive_count, default=1)
    bench.add_argument("--runs", type=positive_count, default=1)
    bench.add_argument("--alone", action="store_true")
    bench.add_argument("command", nargs=argparse.REMAINDER)
    arguments = parser.parse_args(argv)
    if arguments.command[:1] == ["--"]:
        arguments.command = arguments.command[1:]
    if not arguments.command:
        bench.error("give the benchmark command after --")
    return arguments


def main() -> int:
    runner = HeldRunner()
    for stop_signal in STOP_SIGNALS:
        signal.signal(stop_signal, runner.handle_stop_signal)
    if sys.argv[1:2] == ["tool"]:
        return run_tool(parse_tool_run(sys.argv[2:]), runner)
    arguments = parse_bench_arguments(sys.argv[1:])
    return run_benchmark(
        arguments.command, arguments.cores, arguments.alone, arguments.runs, runner
    )


if __name__ == "__main__":
    sys.exit(main())
