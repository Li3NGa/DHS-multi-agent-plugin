# R20 — Scheduler graph lifecycle contract

`Scheduler.run(graph)` consumes the lifecycle state of the supplied `TaskGraph`.

A graph passed to `run()` must be fresh: every task must still be in the `pending`
state. The scheduler owns the transitions `pending -> ready -> running -> terminal`
and therefore rejects graphs containing `ready`, `running`, `completed`, `failed`,
or `cancelled` tasks before execution begins.

This is intentionally fail-fast rather than implicitly resetting task state. Resetting
would require reconstructing or mutating caller-owned execution history and could make
an accidental retry execute with stale dependency/result assumptions.

To execute the same logical workload again, construct a new `TaskGraph` from the
original task specifications.
