# Native Runtime Observability

## Scope

R9 adds a dependency-free lifecycle observer to the Native Scheduler. It is intentionally a hook rather than a logging framework: applications decide whether events go to logs, metrics, tracing, or nowhere.

## Contract

`SchedulerOptions.observer.onEvent` receives these events:

- `run.started`
- `task.started`
- `task.completed`
- `task.failed`
- `task.cancelled`
- `task.blocked`
- `run.completed`

Every event carries a per-run `runId` and timestamp. Task events also carry task/agent identity where available. Failure events may contain the normalized error string.

Observer failures are isolated: an exception thrown by the observer is swallowed and can never change task execution or the returned `SchedulerReport`.

## Design constraints

1. No logging dependency is added to the runtime.
2. No prompts, model output, credentials, or session event payloads are emitted.
3. Observability is synchronous and bounded; there is no background queue or retry loop.
4. `runId` is also returned in `SchedulerReport` so callers can correlate the final result with external telemetry.
5. The observer is opt-in and does not change existing scheduling semantics.

## Next R9 work

Future work can add a stable metrics adapter and recovery lifecycle events without coupling the core scheduler to a telemetry vendor.
