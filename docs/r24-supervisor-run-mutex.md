# R24 — Supervisor instance concurrency contract

A `Supervisor` instance owns one mutable lifecycle state (`created` through a
terminal state) and is therefore single-run at a time.

The supported reuse model is sequential: after one run reaches `completed`,
`failed`, `cancelled`, or `timeout`, the same instance may execute another run.

Starting a second run while the instance is in `validating`, `scheduled`,
`running`, or `aggregating` is rejected before the second call mutates lifecycle
state or dispatches a strategy.

This keeps lifecycle transitions deterministic. Parallel workloads should use
separate `Supervisor` instances (or an outer coordinator that owns per-run state).
