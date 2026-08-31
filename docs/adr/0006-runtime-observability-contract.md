# ADR-0006: Runtime observability contract

## Status

Accepted

## Context

The Native runtime now has bounded scheduling, recovery, retry, repair, replan and cancellation semantics. Production operators need to answer what happened to a run without reading prompts, assistant output or raw DSH session events.

## Decision

Add an optional in-process `RuntimeObserver` to the Native plugin.

The observer receives only these event classes:

- `task.started`
- `task.finished`
- `recovery.started`
- `recovery.attempt`
- `recovery.failure`
- `recovery.decision`
- `recovery.finished`

Events contain identifiers, statuses, failure codes, attempt/repair/replan counts and durations. They deliberately do **not** contain task prompts, assistant text, tool arguments/results, metadata payloads or raw DSH events.

`MetricsCollector` is provided as a zero-dependency in-memory implementation. It can be sampled through `snapshot()` and reset between windows.

Observer callbacks are best effort. Exceptions from an observer are swallowed and must never change execution semantics.

## Consequences

### Positive

- Operators can measure throughput, failures, timeouts, cancellations and recovery activity.
- The event contract is safe to forward to application-owned logging/metrics systems without copying model content.
- Existing users incur no behavior change when observability is omitted.

### Negative

- The collector is process-local and intentionally not a persistence system.
- High-cardinality identifiers remain the caller's responsibility when exporting events.
- Full distributed tracing remains future work.

## Future work

A later phase may add OpenTelemetry adapters without changing the core event contract.
