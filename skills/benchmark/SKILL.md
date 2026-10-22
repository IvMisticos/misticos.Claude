---
name: benchmark
description: Where the `queue` command exists, run every benchmark, profiler run, load test or other timing measurement as `queue bench --` followed by the command in the background, never directly. Run builds and tests through dotnet, cargo, bun and uv in the background too, one at a time, because each waits for a free build slot that other agents share. The queue gives each measurement its own CPU cores, so builds from other agents don't skew the numbers.
---

`queue bench -- <command>` waits until no other benchmark runs, then runs the command on its own core. Other work moves to the remaining cores and keeps running.

- `--cores N` gives the benchmark N cores. Use 1 for native code. Use 2 for .NET, the JVM, Bun and Node, because their JIT compiler and garbage collector run threads beside the measured code. Use more for load tests and parallel benchmarks.
- `--alone` also waits for running builds to finish and holds new builds until the benchmark ends. Builds on other cores still share the CPU cache and memory bandwidth, so use `--alone` when you compare wall-clock times and expect small differences.
- `--runs N` runs the command N times in one hold, so no other benchmark runs between them.

Wrap a compound command in a shell: `queue bench -- bash -c 'cd perf && bun run compare.ts'`.

Run `queue bench` and queued builds in the background: a foreground call that waits in the queue gets killed at the Bash timeout. Wait for the notification that it finished, then read its output.

Builds and tests through `dotnet`, `cargo`, `bun` and `uv` take a build slot on their own. Don't wrap them in `queue`.

On a system that can't pin cores, such as macOS, every benchmark runs alone.

Consider work, not only time.

- `valgrind --tool=cachegrind --cache-sim=no <command>` counts executed instructions and prints the total as `I refs`. It is slow, so use smaller inputs.
- `perf stat -e instructions,cycles <command>` counts with hardware counters at full speed. It needs a CPU that exposes them: if `/sys/bus/event_source/devices/cpu` is missing, as in most cloud VMs, use cachegrind.

## Comparing two versions

Measure only the change in question. For that, fetch the target branch and merge it into the current branch. Build both the same way, unless build settings are being compared.

Run each side once. If the same build has varied before, use `--runs 3` and compare the means.

Make sure the output stays the same. If it differs unintentionally, it is a bug.
