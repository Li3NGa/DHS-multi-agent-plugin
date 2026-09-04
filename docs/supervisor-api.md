# Native Supervisor Contract (Phase E1)

> Frozen Native Supervisor contract. Phase E1 defines the contract **only** —
> there is no executable Supervisor yet (that is Phase E2). This document is the
> single source of truth for what a Supervisor run must look like against the
> frozen Runtime (`packages/dsh-multi-agent/src`).

## Scope

The Native Supervisor is a thin lifecycle + orchestration layer. It:

- owns the **Run lifecycle** (`created → validating → scheduled → running → aggregating → completed`);
- receives an already-ready **plan**, validates it, builds/uses the **TaskGraph**,
  selects a **Strategy**, drives the **Scheduler**, collects the **StrategyReport**,
  and produces a **SupervisorRunResult**.

It does **NOT** implement (these are explicitly out of scope, future phases):

`Planner` · `Router` · `Repair` · `Replan` · `Debate` · `Consensus` · `Persistence` · `HTTP` · `CLI`

## Reuse contract (no duplicate models)

The Supervisor reuses frozen Runtime types verbatim. It MUST NOT create a second
model where one already exists.

| Concept | Frozen source | Notes |
|---|---|---|
| Task / task spec | `src/task.ts` (`Task`, `TaskSpec`) | There is **no** `TaskPlan` in the Runtime; do not invent one |
| Graph | `src/graph.ts` (`TaskGraph`, `GraphError`) | |
| Scheduler | `src/scheduler.ts` (`Scheduler`, `SchedulerReport`, `TaskExecute`) | |
| Task outcomes | `src/runner.ts` (`TaskOutcome`) | live inside `SchedulerReport` / strategy reports |
| Strategy reports | `src/strategies/*` (`BroadcastReport`, `SequentialReport`, `RelayReport`) | consumed via the strategy boundary |
| Strategy options | `src/strategies/*` (`BroadcastOptions`, `SequentialOptions/Step`, `RelayOptions`) | reused as the plan shape |

## Supervisor boundaries

### Strategy boundary

The Supervisor reaches strategies **only** through the frozen Runtime entry
points (`runBroadcast` / `runSequential` / `runRelay` from `src/index.ts`) and
the frozen option/report types. It never copies a strategy's internals.

```ts
export type SupervisorStrategy = 'broadcast' | 'sequential' | 'relay'
```

The plan is a discriminated union reusing the frozen strategy options
(`signal` omitted because the Supervisor owns cancellation):

```ts
export type SupervisorPlan =
  | { strategy: 'broadcast'; options: Omit<BroadcastOptions, 'signal'> }
  | { strategy: 'sequential'; steps: SequentialStep[]; options: Omit<SequentialOptions, 'signal'> }
  | { strategy: 'relay'; options: Omit<RelayOptions, 'signal'> }
```

### Runtime boundary

The Supervisor may depend on: `Task`, `TaskGraph`, `Scheduler`,
Strategy options/reports, `TaskExecute`, error types.

The Supervisor MUST **not** directly access any of:

- `ctx.agents`
- DSH `Session` / `session.events`
- `followup()`
- `agent.cancel()`
- LLM provider / LLM adapter

`AgentRunner` is the only layer that touches these DSH Runtime details.

### TaskPlan boundary

The Runtime has **no** `TaskPlan` type. The Supervisor consumes ready-to-run
plans expressed as the frozen strategy option shapes above. Adding a generic
`TaskPlan` would be a duplicate model and is forbidden.

## SupervisorRunInput

```ts
export interface SupervisorRunInput {
  runId: string
  input: string                      // user intent (opaque to Supervisor)
  plan: SupervisorPlan               // frozen strategy plan
  timeoutMs?: number                 // whole-run ceiling
  signal?: AbortSignal               // host cancellation
  metadata?: Readonly<Record<string, unknown>>
}
```

## SupervisorRunResult

```ts
export type SupervisorRunStatus =
  | 'completed' | 'failed' | 'cancelled' | 'timeout' | 'partial'

export interface SupervisorRunResult {
  runId: string
  status: SupervisorRunStatus
  report: SupervisorStrategyReport    // frozen strategy report (discriminated)
  errors: readonly SupervisorError[]  // top-level errors only
  metadata: Readonly<Record<string, unknown>> | undefined
  durationMs: number
}
```

- `report` is a discriminated union over `BroadcastReport` / `SequentialReport`
  / `RelayReport`. Per-task outcomes and per-task errors stay inside these
  reports; the Supervisor does **not** flatten them into a second `TaskResult`.
- `status: 'partial'` is reserved for future policy (some succeeded, run aborted
  early). The Runtime never produces it.

## Lifecycle

```
created -> validating -> scheduled -> running -> aggregating -> completed
```

Abnormal terminals (only reachable from the phases): `failed`, `cancelled`,
`timeout` (and, in future, `partial`).

Illegal transitions (must be rejected):

- running before scheduled (`created → running`, `validating → running`)
- completed before aggregating
- any transition **out of a terminal** state (`completed/failed/cancelled/timeout`)
- backwards / no-op transitions

The `assertTransition(from, to)` rule (in `src/supervisor/lifecycle.ts`) is the
single source of truth; it throws `SupervisorValidationError` on illegal moves.

## Error model

| Kind | Class | Owner | Semantics |
|---|---|---|---|
| `validation` | `SupervisorValidationError` | Supervisor | plan/input rejected before work |
| `execution` | `SupervisorExecutionError` | Supervisor | wraps **any** Runtime/strategy error; `cause` always preserved |
| `cancellation` | `SupervisorCancellationError` | Supervisor | external `AbortSignal` |
| `timeout` | `SupervisorTimeoutError` | Supervisor | whole-run ceiling |
| `aggregation` | `SupervisorAggregationError` | Supervisor | result aggregation failure |

Runtime errors (`GraphError`, strategy/scheduler failures, per-task `error`)
are **not** re-typed here — they flow through unchanged inside the frozen
reports. The Supervisor never swallows a Runtime error.

## Timeout semantics

The Supervisor reuses the **Phase C Runtime timeout/cancellation** mechanism.
It does **not** implement its own agent timeout, `setTimeout` kill, sleep, or
infinite polling. Whole-run `timeoutMs` maps onto the Runtime's existing
timeout/cancellation semantics via the strategy's `signal`.

## Cancellation semantics

```
AbortSignal ──► Supervisor ──► strategy signal ──► Scheduler ──► Runtime
```

- The Supervisor accepts an `AbortSignal`, stops scheduling new work, forwards
  the cancellation request to the Runtime, and finishes as `cancelled`.
- It never directly manipulates the DSH Session.

## Future extension points

| Concern | Where it plugs in |
|---|---|
| Planner | produces a `SupervisorPlan` before `SupervisorRunInput` |
| Validator | pre-run checks in `validating` phase → `SupervisorValidationError` |
| Router | selects a strategy in `scheduled` phase |
| Repair / Replan | a new `replanning` phase (needs a contract change) |
| Policy (`partial`) | roll-up at `aggregating` → `completed | partial` |

## Files

- `src/supervisor/types.ts` — input / result / status / plan / report types
- `src/supervisor/errors.ts` — error model
- `src/supervisor/lifecycle.ts` — state machine rules
- `src/supervisor/strategy.ts` — strategy boundary (entry-point mapping)
- `src/supervisor/index.ts` — export surface
- `tests/supervisor-contract.test.ts` — Phase E1 contract tests
