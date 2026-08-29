/**
 * Native Supervisor — Phase E1 Error model (contract only).
 *
 * The Supervisor distinguishes its OWN failures (validation, aggregation,
 * cancellation, timeout) from failures that belong to the Runtime. It NEVER
 * swallows a Runtime error: anything raised by TaskGraph / Scheduler /
 * AgentRunner / a Strategy is either surfaced on the result or wrapped in an
 * ExecutionError that preserves the original (`cause`).
 *
 * Error ownership:
 *   - ValidationError     -> Supervisor (plan/input rejected before running)
 *   - CancellationError   -> Supervisor (external AbortSignal)
 *   - TimeoutError        -> Supervisor (whole-run ceiling)
 *   - AggregationError    -> Supervisor (result aggregation)
 *   - ExecutionError      -> wraps ANY Runtime error; original preserved
 *
 * The Runtime's own errors (`GraphError`, strategy errors, task outcomes
 * with `error`) are NOT re-typed here; they flow through unchanged.
 */
import type { SupervisorState } from './types'

/** Discriminated supervisor error kinds. */
export type SupervisorErrorKind =
  | 'validation'
  | 'execution'
  | 'cancellation'
  | 'timeout'
  | 'aggregation'

export interface SupervisorErrorFields {
  /** Stable machine-readable kind. */
  readonly kind: SupervisorErrorKind
  /** Human-readable description. */
  readonly message: string
  /** Original error, when wrapping a Runtime/strategy error (preserved). */
  readonly cause?: unknown | undefined
  /** Lifecycle state at which the error was raised. */
  readonly state?: SupervisorState | undefined
}

/** Base class for every Supervisor-raised error. */
export class SupervisorError extends Error implements SupervisorErrorFields {
  readonly kind: SupervisorErrorKind
  override readonly cause: unknown | undefined
  readonly state: SupervisorState | undefined

  constructor(fields: SupervisorErrorFields) {
    super(fields.message)
    this.name = 'SupervisorError'
    this.kind = fields.kind
    this.cause = fields.cause
    this.state = fields.state
  }
}

/** Plan / input rejected before any work started. */
export class SupervisorValidationError extends SupervisorError {
  constructor(
    message: string,
    fields: { cause?: unknown; state?: SupervisorState } = {},
  ) {
    super({ kind: 'validation', message, ...fields })
    this.name = 'SupervisorValidationError'
  }
}

/**
 * Wraps ANY error raised by the Runtime / a strategy. The original error is
 * always preserved in `cause`; it is never swallowed.
 */
export class SupervisorExecutionError extends SupervisorError {
  constructor(
    message: string,
    fields: { cause: unknown; state?: SupervisorState },
  ) {
    super({ kind: 'execution', message, cause: fields.cause, state: fields.state })
    this.name = 'SupervisorExecutionError'
  }
}

/** External cancellation via AbortSignal. */
export class SupervisorCancellationError extends SupervisorError {
  constructor(
    message: string,
    fields: { cause?: unknown; state?: SupervisorState } = {},
  ) {
    super({ kind: 'cancellation', message, ...fields })
    this.name = 'SupervisorCancellationError'
  }
}

/** Whole-run timeout ceiling exceeded (reuses Runtime timeout semantics). */
export class SupervisorTimeoutError extends SupervisorError {
  constructor(
    message: string,
    fields: { cause?: unknown; state?: SupervisorState } = {},
  ) {
    super({ kind: 'timeout', message, ...fields })
    this.name = 'SupervisorTimeoutError'
  }
}

/** Failure while aggregating strategy/scheduler output into the result. */
export class SupervisorAggregationError extends SupervisorError {
  constructor(
    message: string,
    fields: { cause?: unknown; state?: SupervisorState } = {},
  ) {
    super({ kind: 'aggregation', message, ...fields })
    this.name = 'SupervisorAggregationError'
  }
}

/** Narrow a thrown value to a SupervisorError (for error-boundary tests). */
export function isSupervisorError(value: unknown): value is SupervisorError {
  return value instanceof SupervisorError
}
