#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///

import argparse
import contextlib
import fcntl
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from core_pinning import CAN_PIN_CORES, pinned, plan_cores, restore_abandoned_pinning

HELD_VARIABLE = "HARNESS_QUEUE_HELD"
LOCK_DIR = Path("/tmp") / f"misticos-queue-{os.getuid()}"
MACHINE_LOCK = LOCK_DIR / "machine.lock"
TURNSTILE_LOCK = LOCK_DIR / "turnstile.lock"
BENCHMARK_LOCK = LOCK_DIR / "benchmark.lock"
PINNING_STATE = LOCK_DIR / "pinning.json"
USABLE_CPUS = len(os.sched_getaffinity(0)) if CAN_PIN_CORES else os.cpu_count() or 1
BUILD_SLOTS = max(1, USABLE_CPUS // 2)
SLOT_POLL_SECONDS = 0.5
STOP_SIGNALS = (signal.SIGTERM, signal.SIGHUP)
SIGNALS_PYTHON_IGNORES = (signal.SIGPIPE, signal.SIGXFSZ)
QUEUED_SUBCOMMANDS = {
    "dotnet": {"build", "test", "publish", "pack"},
    "cargo": {
        "build",
        "b",
        "check",
        "c",
        "test",
        "t",
        "bench",
        "clippy",
        "doc",
        "rustc",
        "nextest",
    },
    "bun": {"build", "test"},
    "uv": {"build"},
}
QUEUED_RUN_TARGETS = {
    "bun": {"build", "test"},
    "uv": {"pytest"},
}
PYTHON_LAUNCHERS = {"python", "python3"}
OPTIONS_WITH_VALUE = {
    "cargo": {"-C", "-Z", "--config", "--color"},
    "uv": {
        "--directory",
        "--project",
        "--cache-dir",
        "--config-file",
        "--color",
        "-w",
        "--with",
        "--with-editable",
        "--with-requirements",
        "-p",
        "--python",
        "--package",
        "--extra",
        "--group",
        "--env-file",
        "--index",
    },
    "bun": {"--cwd", "-c", "--config", "-F", "--filter", "--env-file", "--shell"},
}
WATCH_FLAGS = {"--watch", "--hot"}


def positionals(tool, arguments):
    options_with_value = OPTIONS_WITH_VALUE.get(tool, set())
    words = iter(arguments)
    for word in words:
        if word in options_with_value:
            next(words, None)
        elif not word.startswith(("-", "+")):
            yield word


def queues(tool, arguments):
    if WATCH_FLAGS & set(arguments):
        return False
    match list(positionals(tool, arguments)):
        case [subcommand, *_] if subcommand in QUEUED_SUBCOMMANDS.get(tool, ()):
            return True
        case ["run", launcher, target, *_] if launcher in PYTHON_LAUNCHERS:
            return target in QUEUED_RUN_TARGETS.get(tool, ())
        case ["run", target, *_]:
            return target in QUEUED_RUN_TARGETS.get(tool, ())
    return False


def notice(message):
    print(f"queue: {message}", file=sys.stderr, flush=True)


def open_lock_file(path):
    LOCK_DIR.mkdir(mode=0o700, exist_ok=True)
    if LOCK_DIR.lstat().st_uid != os.getuid():
        sys.exit(f"queue: {LOCK_DIR} belongs to another user")
    return open(path, "a")


def lock_now(handle, operation):
    try:
        fcntl.flock(handle, operation | fcntl.LOCK_NB)
    except BlockingIOError:
        return False
    return True


def try_lock(path, operation):
    handle = open_lock_file(path)
    if lock_now(handle, operation):
        return handle
    handle.close()
    return None


@contextlib.contextmanager
def locked(path, operation, waiting_message):
    with open_lock_file(path) as handle:
        if not lock_now(handle, operation):
            notice(waiting_message)
            fcntl.flock(handle, operation)
        yield


@contextlib.contextmanager
def machine_locked(operation, waiting_message):
    with open_lock_file(MACHINE_LOCK) as machine:
        with open_lock_file(TURNSTILE_LOCK) as turnstile:
            if not (
                lock_now(turnstile, fcntl.LOCK_EX) and lock_now(machine, operation)
            ):
                notice(waiting_message)
                fcntl.flock(turnstile, fcntl.LOCK_EX)
                fcntl.flock(machine, operation)
        yield


def free_build_slot():
    for index in range(BUILD_SLOTS):
        slot = try_lock(LOCK_DIR / f"build-{index}.lock", fcntl.LOCK_EX)
        if slot:
            return slot
    return None


@contextlib.contextmanager
def build_slot():
    slot = free_build_slot()
    if slot is None:
        notice("waiting for a build slot")
    while slot is None:
        time.sleep(SLOT_POLL_SECONDS)
        slot = free_build_slot()
    with slot:
        yield


def exit_status(returncode):
    return 128 - returncode if returncode < 0 else returncode


def run_held(command):
    environment = {**os.environ, HELD_VARIABLE: "1"}
    child = subprocess.Popen(command, env=environment)

    def forward_to_child(signal_number, _frame):
        child.send_signal(signal_number)

    for stop_signal in STOP_SIGNALS:
        signal.signal(stop_signal, forward_to_child)
    return exit_status(child.wait())


def restore_pinning_of_killed_benchmark():
    if not CAN_PIN_CORES:
        return
    benchmark = try_lock(BENCHMARK_LOCK, fcntl.LOCK_EX)
    if benchmark is None:
        return
    with benchmark:
        restore_abandoned_pinning(PINNING_STATE)


def run_build(command):
    restore_pinning_of_killed_benchmark()
    alone_message = "waiting for a benchmark that runs alone"
    with build_slot(), machine_locked(fcntl.LOCK_SH, alone_message):
        return run_held(command)


def exec_unqueued(executable, arguments):
    for ignored_signal in SIGNALS_PYTHON_IGNORES:
        signal.signal(ignored_signal, signal.SIG_DFL)
    os.execv(executable, [executable, *arguments])


def run_tool(executable, arguments):
    if not queues(Path(executable).name, arguments):
        exec_unqueued(executable, arguments)
    return run_build([executable, *arguments])


def run_benchmark(command, cores, alone):
    if not CAN_PIN_CORES and not alone:
        notice("this system cannot pin cores, so the benchmark runs alone")
        alone = True
    with contextlib.ExitStack() as held:
        held.enter_context(
            locked(BENCHMARK_LOCK, fcntl.LOCK_EX, "waiting for the running benchmark")
        )
        if CAN_PIN_CORES:
            restore_abandoned_pinning(PINNING_STATE)
        plan = plan_cores(cores, alone) if CAN_PIN_CORES else None
        if alone:
            held.enter_context(
                machine_locked(fcntl.LOCK_EX, "waiting for builds to finish")
            )
        if plan:
            held.enter_context(pinned(plan, PINNING_STATE))
        return run_held(command)


def positive_count(text):
    count = int(text)
    if count < 1:
        raise argparse.ArgumentTypeError("needs at least 1")
    return count


def parse_bench_arguments():
    parser = argparse.ArgumentParser(prog="queue")
    modes = parser.add_subparsers(dest="mode", required=True)
    bench = modes.add_parser("bench")
    bench.add_argument("--cores", type=positive_count, default=1)
    bench.add_argument("--alone", action="store_true")
    bench.add_argument("command", nargs=argparse.REMAINDER)
    arguments = parser.parse_args()
    if arguments.command[:1] == ["--"]:
        arguments.command = arguments.command[1:]
    if not arguments.command:
        bench.error("give the benchmark command after --")
    return arguments


def exit_on_signal(signal_number, _frame):
    sys.exit(128 + signal_number)


def main():
    for stop_signal in STOP_SIGNALS:
        signal.signal(stop_signal, exit_on_signal)
    if sys.argv[1:2] == ["tool"]:
        return run_tool(sys.argv[2], sys.argv[3:])
    arguments = parse_bench_arguments()
    return run_benchmark(arguments.command, arguments.cores, arguments.alone)


if __name__ == "__main__":
    sys.exit(main())
