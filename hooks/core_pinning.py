import contextlib
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

CAN_PIN_CORES = hasattr(os, "sched_setaffinity")


@dataclass(frozen=True)
class CorePlan:
    everything: frozenset[int]
    benchmark: frozenset[int]
    reserved: frozenset[int]

    @property
    def others(self):
        return self.everything - self.reserved


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


def all_threads():
    for task in Path("/proc").glob("[0-9]*/task/[0-9]*"):
        yield int(task.name)


def move_off_reserved_cores(plan):
    original_masks = {}
    if not plan.others:
        return original_masks
    for thread in all_threads():
        with contextlib.suppress(OSError):
            mask = os.sched_getaffinity(thread)
            if mask & plan.reserved:
                os.sched_setaffinity(thread, (mask - plan.reserved) or plan.others)
                original_masks[thread] = mask
    return original_masks


def restore_threads(plan, original_masks):
    for thread in all_threads():
        with contextlib.suppress(OSError):
            if thread in original_masks:
                os.sched_setaffinity(thread, original_masks[thread])
            elif os.sched_getaffinity(thread) in (plan.others, plan.benchmark):
                os.sched_setaffinity(thread, plan.everything)


def save_pinning(state_path, plan, original_masks):
    state = {
        "everything": sorted(plan.everything),
        "benchmark": sorted(plan.benchmark),
        "reserved": sorted(plan.reserved),
        "original_masks": {
            str(thread): sorted(mask) for thread, mask in original_masks.items()
        },
    }
    state_path.write_text(json.dumps(state))


def load_pinning(state_path):
    try:
        state = json.loads(state_path.read_text())
    except FileNotFoundError:
        return None
    plan = CorePlan(
        frozenset(state["everything"]),
        frozenset(state["benchmark"]),
        frozenset(state["reserved"]),
    )
    original_masks = {
        int(thread): set(mask) for thread, mask in state["original_masks"].items()
    }
    return plan, original_masks


def restore_abandoned_pinning(state_path):
    abandoned = load_pinning(state_path)
    if abandoned is None:
        return
    restore_threads(*abandoned)
    state_path.unlink()


@contextlib.contextmanager
def pinned(plan, state_path):
    original_masks = {}
    try:
        original_masks = move_off_reserved_cores(plan)
        save_pinning(state_path, plan, original_masks)
        os.sched_setaffinity(0, plan.benchmark)
        yield
    finally:
        restore_threads(plan, original_masks)
        state_path.unlink(missing_ok=True)
