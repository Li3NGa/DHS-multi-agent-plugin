/**
 * Native Planner — Phase E3 error model.
 *
 * The Planner layer has its own error types, kept distinct from the frozen
 * Supervisor error model (SupervisorError). A Planner error is a planning /
 * parsing / validation failure that happens BEFORE the Supervisor runs; the
 * Supervisor never sees these.
 *
 * All Planner errors share a `kind` tag and optionally an `issues` array so
 * callers can drive UI / retry decisions without parsing message strings.
 */
import type { PlanIssue } from './types'

export type PlannerErrorKind =
  | 'parse' // raw plan text could not be parsed into tasks
  | 'validation' // the plan failed structural validation
  | 'routing' // a task could not be assigned an agent
  | 'integration' // a validated plan could not be mapped to a Supervisor plan

/** Base class for every planner-layer error. */
export abstract class PlannerError extends Error {
  abstract readonly kind: PlannerErrorKind

  constructor(message: string) {
    super(message)
    this.name = new.target.name
  }
}

/** Raw planner output could not be parsed into a task list. */
export class PlanParseError extends PlannerError {
  readonly kind = 'parse' as const
}

/** A planned task list failed structural validation. */
export class PlanValidationError extends PlannerError {
  readonly kind = 'validation' as const
  readonly issues: readonly PlanIssue[]

  constructor(message: string, issues: readonly PlanIssue[] = []) {
    super(message)
    this.issues = issues
  }
}

/** A task could not be assigned a concrete agent. */
export class PlanRoutingError extends PlannerError {
  readonly kind = 'routing' as const
  readonly taskId: string | undefined

  constructor(message: string, taskId?: string) {
    super(message)
    this.taskId = taskId
  }
}

/** A validated, routed plan could not be mapped to a SupervisorPlan. */
export class PlanIntegrationError extends PlannerError {
  readonly kind = 'integration' as const
}

/** Narrowing guard for planner-layer errors. */
export function isPlannerError(error: unknown): error is PlannerError {
  return error instanceof PlannerError
}
