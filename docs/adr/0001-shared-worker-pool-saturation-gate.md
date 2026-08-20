# ADR 0001: Shared worker pool saturation gate

- Status: accepted
- Date: 2026-08-21

## Context

All agent calls and scheduled tasks in the process run on one bounded
`ThreadPoolExecutor` (`shared_executor`, default 16 workers,
`DSMA_MAX_CONCURRENCY`). Because Python threads cannot be killed, a
timed-out call keeps occupying its worker until its own I/O timeout fires.
With many concurrent runs, slow workers can therefore make the executor's
internal queue grow without bound: `submit()` parks tasks behind them, and
each queued task later pays the full per-call timeout on top of the queueing
delay.

## Decision

Wrap the pool in a counting gate (`BoundedSemaphore(max_workers)`):

- `submit()` acquires a slot before dispatching and releases it when the
  wrapped callable finishes.
- If no slot frees up within `DSMA_POOL_SLOT_TIMEOUT` (default 1s), the
  call is **not** queued: `PoolSaturated` is raised instead.
- Strategies (`_call_agent`, `_parallel`) and the DAG scheduler treat
  saturation like a timeout — the agent result becomes
  `{"error": "timeout"}` / task status `TIMEOUT` with `"pool saturated"`
  detail, or `RunTimeout` when a run deadline is active.

## Consequences

- Queue depth behind slow workers is bounded by `max_workers`, and every
  failed submission degrades in O(slot timeout) instead of O(queue length).
- Callers keep a result (or exception) for every agent, preserving the
  existing result contract.
- `shared_executor()` keeps its `submit()/shutdown()` API, so existing
  call sites are unchanged; `PoolSaturated` is a new exception type.
