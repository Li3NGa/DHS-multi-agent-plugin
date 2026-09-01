# ADR-0007: Production diagnostics

## Status
Accepted

## Decision

R10 exposes a bounded, in-process diagnostic surface built on R9 telemetry. `MultiAgentApi.diagnostics()` returns a `RuntimeDiagnostics` instance with:

- `health()` — health/readiness-style runtime snapshot;
- `inspect(runId)` — one run's bounded operational history;
- `recentRuns(limit)` — newest-first bounded run history;
- `registry` — explicit lifecycle registry for integrations.

The default plugin instance creates its own `MetricsCollector` and diagnostics registry. A caller may inject a preconfigured `RuntimeDiagnostics` through `PluginConfig.diagnostics`.

Diagnostic state contains only operational identifiers, statuses, failure codes, attempts, recovery decisions and timings. Prompts, model output, tool payloads and raw DSH session events are excluded.

Run history is bounded (default 256) to prevent unbounded memory growth. Diagnostics are process-local and are not a persistence or distributed tracing system.

## Health semantics

- `healthy`: no active runs and no recorded failure signal requiring degradation.
- `degraded`: active work or recoverable failures are present.
- `unhealthy`: recovery timeouts exist, or failures exist without any completed task signal.

These are conservative operational signals, not SLA or business-health assertions.
