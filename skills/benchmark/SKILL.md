---
name: benchmark
description: Where the `queue` command exists, run every benchmark, profiler run, load test or other timing measurement as `queue bench -- <command>`, never directly. The queue gives the measurement its own CPU cores, so builds from other agents don't skew the numbers.
---

`queue bench -- <command>` waits until no other benchmark runs, then runs the command on its own core. Other work moves to the remaining cores and keeps running.

- `--cores N` gives the benchmark N cores. Use 1 for native code. Use 2 for .NET, the JVM, Bun and Node, because their JIT compiler and garbage collector run threads beside the measured code. Use more for load tests and parallel benchmarks.
- `--alone` also waits for running builds to finish and holds new builds until the benchmark ends. Builds on other cores still share the CPU cache and memory bandwidth, so use `--alone` when you compare wall-clock times and expect small differences.

Wrap a compound command in a shell: `queue bench -- bash -c 'cd perf && bun run compare.ts'`.

A hook runs every `queue bench` call in the background. Wait for the notification that it finished, then read its output.

Builds and tests through `dotnet`, `cargo`, `bun` and `uv` take a build slot on their own. Don't wrap them in `queue`.

On a system that can't pin cores, such as macOS, every benchmark runs alone.
