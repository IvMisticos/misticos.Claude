#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///

import argparse
import contextlib
import fcntl
import functools
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

HELD_VARIABLE = "MISTICOS_QUEUE_HELD"
LOCK_DIR = Path("/tmp") / f"misticos-queue-{os.getuid()}"
MACHINE_LOCK = LOCK_DIR / "machine.lock"
TURNSTILE_LOCK = LOCK_DIR / "turnstile.lock"
BENCHMARK_LOCK = LOCK_DIR / "benchmark.lock"
BUILD_SLOTS = max(1, (os.cpu_count() or 1) // 2)
SLOT_POLL_SECONDS = 0.5
CAN_PIN_CORES = hasattr(os, "sched_setaffinity")
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
    },
    "bun": {"build", "test"},
    "uv": {"build"},
}
QUEUED_RUN_TARGETS = {
    "bun": {"build", "test"},
    "uv": {"pytest"},
}
GLOBAL_OPTIONS_WITH_VALUE = {
    "cargo": {"-C", "-Z", "--config", "--color"},
    "uv": {"--directory", "--project", "--cache-dir", "--config-file", "--color"},
    "bun": {"--cwd", "--config", "-c"},
}


@dataclass(frozen=True)
class CorePlan:
    everything: frozenset[int]
    benchmark: frozenset[int]
    reserved: frozenset[int]

    @property
    def others(self):
        return self.everything - self.reserved


def positionals(tool, arguments):
    options_with_value = GLOBAL_OPTIONS_WITH_VALUE.get(tool, set())
    words = iter(arguments)
    for word in words:
        if word in options_with_value:
            next(words, None)
        elif not word.startswith(("-", "+")):
            yield word


def queues(tool, arguments):
    words = list(positionals(tool, arguments))
    if not words:
        return False
    subcommand, *rest = words
    if subcommand in QUEUED_SUBCOMMANDS.get(tool, ()):
        return True
    return subcommand == "run" and bool(QUEUED_RUN_TARGETS.get(tool, set()) & set(rest))


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


def build_would_wait():
    probes = (
        free_build_slot,
        functools.partial(try_lock, TURNSTILE_LOCK, fcntl.LOCK_EX),
        functools.partial(try_lock, MACHINE_LOCK, fcntl.LOCK_SH),
    )
    with contextlib.ExitStack() as taken:
        for probe in probes:
            handle = probe()
            if handle is None:
                return True
            taken.enter_context(handle)
    return False


def hyperthreads(cpu):
    listing = Path(f"/sys/devices/system/cpu/cpu{cpu}/topology/thread_siblings_list")
    try:
        text = listing.read_text().strip()
    except OSError:
        return {cpu}
    siblings = {cpu}
    for part in text.split(","):
        first, _, last = part.partition("-")
        siblings.update(range(int(first), int(last or first) + 1))
    return siblings


def plan_cores(count, alone):
    everything = frozenset(os.sched_getaffinity(0))
    benchmark, reserved = set(), set()
    for cpu in sorted(everything, reverse=True):
        if len(benchmark) == count:
            break
        if cpu not in reserved:
            benchmark.add(cpu)
            reserved |= hyperthreads(cpu) & everything
    if len(benchmark) < count:
        sys.exit(f"queue: --cores {count} asks for more cores than this machine has")
    if reserved == everything and not alone:
        sys.exit(
            f"queue: --cores {count} leaves no core for other work. "
            "Pass --alone to use every core."
        )
    return CorePlan(everything, frozenset(benchmark), frozenset(reserved))


def other_threads():
    own_process = str(os.getpid())
    for task in Path("/proc").glob("[0-9]*/task/[0-9]*"):
        if task.parent.parent.name != own_process:
            yield int(task.name)


def move_off_reserved_cores(plan):
    original_masks = {}
    for thread in other_threads():
        with contextlib.suppress(OSError):
            mask = os.sched_getaffinity(thread)
            if mask & plan.reserved:
                os.sched_setaffinity(thread, (mask - plan.reserved) or plan.others)
                original_masks[thread] = mask
    return original_masks


def restore_moved_threads(plan, original_masks):
    for thread in other_threads():
        with contextlib.suppress(OSError):
            if thread in original_masks:
                os.sched_setaffinity(thread, original_masks[thread])
            elif os.sched_getaffinity(thread) in (plan.others, plan.benchmark):
                os.sched_setaffinity(thread, plan.everything)


@contextlib.contextmanager
def pinned(plan):
    original_masks = move_off_reserved_cores(plan) if plan.others else {}
    os.sched_setaffinity(0, plan.benchmark)
    try:
        yield
    finally:
        os.sched_setaffinity(0, plan.everything)
        restore_moved_threads(plan, original_masks)


def exit_status(returncode):
    return 128 - returncode if returncode < 0 else returncode


def run_held(command):
    environment = {**os.environ, HELD_VARIABLE: "1"}
    return exit_status(subprocess.run(command, env=environment, check=False).returncode)


def run_build(command):
    alone_message = "waiting for a benchmark that runs alone"
    with build_slot(), machine_locked(fcntl.LOCK_SH, alone_message):
        return run_held(command)


def run_tool(executable, arguments):
    if not queues(Path(executable).name, arguments):
        os.execv(executable, [executable, *arguments])
    return run_build([executable, *arguments])


def run_benchmark(command, cores, alone):
    if not CAN_PIN_CORES and not alone:
        notice("this system cannot pin cores, so the benchmark runs alone")
        alone = True
    plan = plan_cores(cores, alone) if CAN_PIN_CORES else None
    with contextlib.ExitStack() as held:
        held.enter_context(
            locked(BENCHMARK_LOCK, fcntl.LOCK_EX, "waiting for the running benchmark")
        )
        if alone:
            held.enter_context(
                machine_locked(fcntl.LOCK_EX, "waiting for builds to finish")
            )
        if plan:
            held.enter_context(pinned(plan))
        return run_held(command)


def positive_count(text):
    count = int(text)
    if count < 1:
        raise argparse.ArgumentTypeError("needs at least 1")
    return count


def parse_arguments():
    parser = argparse.ArgumentParser(prog="queue")
    modes = parser.add_subparsers(dest="mode", required=True)
    bench = modes.add_parser("bench")
    bench.add_argument("--cores", type=positive_count, default=1)
    bench.add_argument("--alone", action="store_true")
    bench.add_argument("command", nargs=argparse.REMAINDER)
    tool = modes.add_parser("tool")
    tool.add_argument("executable")
    tool.add_argument("arguments", nargs=argparse.REMAINDER)
    arguments = parser.parse_args()
    if arguments.mode == "bench":
        if arguments.command[:1] == ["--"]:
            arguments.command = arguments.command[1:]
        if not arguments.command:
            bench.error("give the benchmark command after --")
    return arguments


def exit_on_signal(signal_number, _frame):
    sys.exit(128 + signal_number)


def main():
    arguments = parse_arguments()
    for stop_signal in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(stop_signal, exit_on_signal)
    if arguments.mode == "tool":
        return run_tool(arguments.executable, arguments.arguments)
    return run_benchmark(arguments.command, arguments.cores, arguments.alone)


if __name__ == "__main__":
    sys.exit(main())
