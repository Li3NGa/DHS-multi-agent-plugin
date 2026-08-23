/**
 * Native Supervisor — Phase E1 Contract (types only).
 *
 * This module is the FROZEN Supervisor contract. It defines the shapes the
 * Supervisor exposes to the world and the shapes it consumes from the
 * (frozen) Runtime. It MUST NOT introduce duplicate models: everything that
 * already exists in the Runtime is reused verbatim (`Task`, `TaskGraph`,
 * `SchedulerReport`, `TaskOutcome`, the strategy option/report types).
 *
 * The Supervisor itself is NOT implemented here (that is Phase E2). This
 * file only pins the contract so E2 can implement against a stable surface.
 *
 * Contract sections (see docs/supervisor-api.md):
 *   - SupervisorRunInput
 *   - SupervisorRunResult
 *   - SupervisorStatus / lifecycle
 *   - Error model (errors.ts)
 *   - Timeout semantics
 *   - Cancellation semantics
 *   - Strategy boundary
 *   - Runtime boundary
 *   - Future Planner/Validator/Router extension points
 */
import type { SchedulerReport } from '../scheduler'
import type { BroadcastReport, BroadcastOptions } from '../strategies/broadcast'
import type { SequentialReport, SequentialOptions, SequentialStep } from '../strategies/sequential'
import type { RelayReport, RelayOptions } from '../strategies/relay'
import type { SupervisorError } from './errors'

/**
 * The strategy a Supervisor run executes. The Supervisor never touches a
 * strategy's internals — it only references one by name and consumes the
 * corresponding frozen report type (see {@link SupervisorRunResult.report}).
 *
 * This is the STRATEGY BOUNDARY: adding a strategy is a contract change, not
 * a Supervisor change.
 */
export type SupervisorStrategy = 'broadcast' | 'sequential' | 'relay'

/**
 * The plan for one strategy run, reusing the frozen strategy option types.
 *
 * No duplicate models: these ARE the same option shapes the Runtime's
 * `runBroadcast` / `runSequential` / `runRelay` accept. `signal` is omitted
 * because the Supervisor owns cancellation and maps its own AbortSignal onto
 * the Runtime; `concurrency` is a Runtime-level concern and passes through
 * as-is.
 *
 * There is deliberately NO generic `TaskPlan` here: the frozen Runtime has no
 * such type, and inventing one would be a duplicate model. Each strategy has
 * its own plan shape, and the Supervisor only speaks to strategies through
 * this discriminated union (the Strategy boundary).
 */
export type SupervisorPlan =
  | {
      readonly strategy: 'broadcast'
      readonly options: Omit<BroadcastOptions, 'signal'>
    }
  | {
      readonly strategy: 'sequential'
      readonly steps: readonly SequentialStep[]
      readonly options: Omit<SequentialOptions, 'signal'>
    }
  | {
      readonly strategy: 'relay'
      readonly options: Omit<RelayOptions, 'signal'>
    }

/** Discriminated union over the frozen strategy report types. */
export type SupervisorStrategyReport =
  | { readonly strategy: 'broadcast'; readonly report: BroadcastReport }
  | { readonly strategy: 'sequential'; readonly report: SequentialReport }
  | { readonly strategy: 'relay'; readonly report: RelayReport }

/**
 * Terminal run statuses. `partial` is not produced by the runtime; it is a
 * Supervisor-level roll-up meaning "some tasks succeeded, run aborted early"
 * and is reserved for future policy (Phase E2+). The frozen Runtime only
 * knows per-task statuses; the Supervisor must NOT invent a second
 * TaskResult model to carry them.
 */
export type SupervisorRunStatus =
  | 'completed'
  | 'failed'
  | 'cancelled'
  | 'timeout'
  | 'partial'

/** Non-terminal lifecycle states (internal, see lifecycle.ts). */
export type SupervisorPhase =
  | 'created'
  | 'validating'
  | 'scheduled'
  | 'running'
  | 'aggregating'

export type SupervisorState = SupervisorPhase | SupervisorRunStatus

/**
 * Minimal input for one Supervisor run. Reuses the frozen strategy plan
 * types; the Supervisor does not redefine a plan model.
 */
export interface SupervisorRunInput {
  /** Stable identity of this run. */
  readonly runId: string
  /** User intent / entry prompt (opaque to the Supervisor). */
  readonly input: string
  /** Ready-to-run strategy plan (discriminated union of frozen options). */
  readonly plan: SupervisorPlan
  /** Whole-run timeout ceiling in ms (reuses Runtime timeout semantics). */
  readonly timeoutMs?: number
  /** Host cancellation signal; mapped onto Runtime cancellation. */
  readonly signal?: AbortSignal
  /** Opaque metadata carried through and echoed on the result. */
  readonly metadata?: Readonly<Record<string, unknown>>
}

/**
 * Result of one Supervisor run.
 *
 * Reuse contract: the individual task outcomes live inside the frozen
 * strategy report (which wraps the `SchedulerReport`). The Supervisor does
 * NOT flatten them into a second TaskResult model. `errors` collects the
 * top-level (Supervisor-level) errors only; per-task errors remain in the
 * strategy/scheduler report.
 */
export interface SupervisorRunResult {
  readonly runId: string
  readonly status: SupervisorRunStatus
  /** The aggregated strategy report (frozen types only). */
  readonly report: SupervisorStrategyReport
  /** Top-level error(s), if the run did not complete normally. */
  readonly errors: readonly SupervisorError[]
  /** Echo of the input metadata. */
  readonly metadata: Readonly<Record<string, unknown>> | undefined
  /** Wall-clock duration of the run in ms (0 until aggregated). */
  readonly durationMs: number
}

/**
 * Reference to the underlying frozen SchedulerReport when a consumer needs
 * the raw scheduler view. Exposed for observability only; the Supervisor
 * contract itself is the strategy report above.
 */
export type SupervisorSchedulerReport = SchedulerReport
