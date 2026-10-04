import contextlib
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

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


class Thread(NamedTuple):
    id: int
    started: int


def started_at(task_path):
    fields_after_name = (Path(task_path) / "stat").read_text().rsplit(")", 1)[1]
    return int(fields_after_name.split()[19])


def listed(directory):
    try:
        with os.scandir(directory) as entries:
            return list(entries)
    except OSError:
        return []


def live_threads():
    for process in listed("/proc"):
        if not process.name.isdigit():
            continue
        for task in listed(os.path.join(process.path, "task")):
            try:
                started = started_at(task.path)
            except OSError:
                continue
            yield Thread(int(task.name), started)


def snapshot_masks():
    masks = {}
    for thread in live_threads():
        with contextlib.suppress(OSError):
            masks[thread] = os.sched_getaffinity(thread.id)
    return masks


def threads_born_on_reserved_cores(plan, known_threads):
    return {
        thread: mask
        for thread, mask in snapshot_masks().items()
        if thread not in known_threads and mask & plan.reserved
    }


def move_off_reserved_cores(plan, masks_before):
    moved = 0
    for thread, mask in masks_before.items():
        if not mask & plan.reserved:
            continue
        try:
            os.sched_setaffinity(thread.id, (mask - plan.reserved) or plan.others)
        except OSError:
            continue
        moved += 1
    return moved


def restore_threads(plan, masks_before):
    for thread in live_threads():
        with contextlib.suppress(OSError):
            if thread in masks_before:
                os.sched_setaffinity(thread.id, masks_before[thread])
            elif os.sched_getaffinity(thread.id) in (plan.others, plan.benchmark):
                os.sched_setaffinity(thread.id, plan.everything)


def save_pinning(state_path, plan, masks_before):
    state = {
        "everything": sorted(plan.everything),
        "benchmark": sorted(plan.benchmark),
        "reserved": sorted(plan.reserved),
        "masks_before": {
            f"{thread.id}:{thread.started}": sorted(mask)
            for thread, mask in masks_before.items()
        },
    }
    staged = state_path.with_name(state_path.name + ".saving")
    staged.write_text(json.dumps(state))
    os.replace(staged, state_path)


def load_pinning(state_path):
    try:
        state = json.loads(state_path.read_text())
        plan = CorePlan(
            frozenset(state["everything"]),
            frozenset(state["benchmark"]),
            frozenset(state["reserved"]),
        )
        masks_before = {
            Thread(*map(int, thread.split(":"))): set(mask)
            for thread, mask in state["masks_before"].items()
        }
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return plan, masks_before


def restore_abandoned_pinning(state_path):
    abandoned = load_pinning(state_path)
    if abandoned:
        restore_threads(*abandoned)
    state_path.unlink(missing_ok=True)


def clear_reserved_cores(plan, masks_before, state_path):
    move_off_reserved_cores(plan, masks_before)
    while late := threads_born_on_reserved_cores(plan, masks_before):
        masks_before |= late
        save_pinning(state_path, plan, masks_before)
        if not move_off_reserved_cores(plan, late):
            return


@contextlib.contextmanager
def pinned(plan, state_path):
    masks_before = snapshot_masks()
    save_pinning(state_path, plan, masks_before)
    try:
        if plan.others:
            clear_reserved_cores(plan, masks_before, state_path)
        os.sched_setaffinity(0, plan.benchmark)
        yield
    finally:
        restore_threads(plan, masks_before)
        state_path.unlink(missing_ok=True)
