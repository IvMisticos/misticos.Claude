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

## Comparing two versions

Compare the branch against latest main. Fetch main first and merge it into the branch, so the only difference is the change you measure. Build both the same way, such as Release with the same flags and runtime, unless the build setting is what you compare.

Count work, not only time. Instructions and allocated bytes barely change between runs, so they show a small change that wall time hides in noise. Allocations count as much as CPU time.

- `valgrind --tool=cachegrind --cache-sim=no <command>` counts instructions (`I refs`) for native code. It runs many times slower, so give it a smaller input.
- `perf stat -e instructions,cycles <command>` counts with hardware counters at full speed. It needs a CPU that exposes them: if `/sys/bus/event_source/devices/cpu` is missing, as in most cloud VMs, use cachegrind.
- For .NET, BenchmarkDotNet with `[MemoryDiagnoser]` reports allocated bytes per operation.

Run each side once, unless two runs of the same build have differed before. Then run each side with `queue bench --runs 3` and report the mean and the change in percent.

Before you report a result, check two things:

- Both versions give the same output for the same input. A faster version that computes something else is a bug, not a speedup. Compare the outputs or their hashes.
- The measurement covers everything the claim names. If you claim a faster request, time the whole request on the full current setup, not only the parsing step or a stripped-down setup. A partial measurement can be wrong by a factor of 10.
