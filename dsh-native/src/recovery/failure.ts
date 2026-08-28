/**
 * Native Recovery — Phase E4 Failure Classifier.
 *
 * Deterministic mapping from a failed execution (thrown error OR
 * SupervisorRunResult) to a FailureRecord. Classification NEVER guesses a
 * recovery: it only labels the failure and consults the frozen
 * recoverability table below. Unknown runtime errors default to "no
 * automatic recovery" (phase contract).
 *
 * Task-level markers (from AgentRunner outcomeFromEvents):
 *   - error starts with 'timeout:'            -> TIMEOUT
 *   - error matches /agent '.+' not found/    -> AGENT_UNAVAILABLE
 *   - status 'cancelled' + 'dependency ...'   -> DEPENDENCY_FAILURE (cascade)
 *   - other cancelled                          -> CANCELLED
 *   - anything else                            -> TASK_ERROR
 *
 * Run-level primary-code priority when several tasks failed:
 *   AGENT_UNAVAILABLE > DEPENDENCY_FAILURE > TIMEOUT > CANCELLED > TASK_ERROR
 * (most structurally-specific recoverable class wins).
 */
import type { SupervisorRunResult } from '../supervisor'
import { isSupervisorError } from '../supervisor'
import { PlanIntegrationError, PlanParseError, PlanRoutingError } from '../planner/errors'
import { PlanValidationError as PlanValidationErrorPlanner } from '../planner/errors'
import { GraphError } from '../graph'
import type {
  FailureCode,
  FailureRecord,
  Recoverability,
  TaskFailureRef,
} from './types'

/** Frozen recoverability matrix (phase contract section 六). */
export const RECOVERABILITY: Readonly<Record<FailureCode, Recoverability>> = Object.freeze({
  VALIDATION_ERROR: { retryable: false, repairable: false, replanable: false, fatal: true },
  ROUTING_ERROR: { retryable: false, repairable: false, replanable: false, fatal: true },
  TASK_ERROR: { retryable: false, repairable: false, replanable: false, fatal: false },
  TIMEOUT: { retryable: true, repairable: false, replanable: false, fatal: false },
  CANCELLED: { retryable: false, repairable: false, replanable: false, fatal: true },
  DEPENDENCY_FAILURE: { retryable: false, repairable: false, replanable: true, fatal: false },
  AGENT_UNAVAILABLE: { retryable: false, repairable: true, replanable: false, fatal: false },
  STRATEGY_ERROR: { retryable: false, repairable: false, replanable: false, fatal: false },
  RUNTIME_ERROR: { retryable: false, repairable: false, replanable: false, fatal: false },
})

const PRIORITY: readonly FailureCode[] = [
  'AGENT_UNAVAILABLE',
  'DEPENDENCY_FAILURE',
  'TIMEOUT',
  'CANCELLED',
  'TASK_ERROR',
]

function nowIso(): string {
  return new Date().toISOString()
}

function record(
  code: FailureCode,
  message: string,
  attempt: number,
  extra: Partial<FailureRecord> = {},
): FailureRecord {
  return {
    code,
    message,
    attempt,
    recoverability: RECOVERABILITY[code],
    timestamp: nowIso(),
    thrown: extra.thrown ?? false,
    ...(extra.cause !== undefined ? { cause: extra.cause } : {}),
    ...(extra.taskId !== undefined ? { taskId: extra.taskId } : {}),
    ...(extra.agentId !== undefined ? { agentId: extra.agentId } : {}),
    ...(extra.taskFailures !== undefined ? { taskFailures: extra.taskFailures } : {}),
  }
}

function codeForTaskOutcome(status: string, error: string | undefined): FailureCode {
  if (status === 'cancelled') {
    return error !== undefined && error.startsWith('dependency ')
      ? 'DEPENDENCY_FAILURE'
      : 'CANCELLED'
  }
  if (error === undefined) return 'TASK_ERROR'
  if (error.startsWith('timeout:')) return 'TIMEOUT'
  if (/^agent '[^']+' not found$/.test(error)) return 'AGENT_UNAVAILABLE'
  return 'TASK_ERROR'
}

interface ReportEntryLike {
  readonly taskId: string | undefined
  readonly agentId: string | undefined
  readonly status: string
  readonly error: string | undefined
}

/** Extract every non-completed task entry from the frozen report shapes. */
export function extractTaskFailures(result: SupervisorRunResult): readonly TaskFailureRef[] {
  const report = result.report.report as unknown as {
    readonly responses?: readonly Record<string, unknown>[]
    readonly steps?: readonly Record<string, unknown>[]
    readonly turns?: readonly Record<string, unknown>[]
  }
  const entries: ReportEntryLike[] = []
  for (const group of [report.responses, report.steps, report.turns]) {
    if (!Array.isArray(group)) continue
    for (const entry of group as Record<string, unknown>[]) {
      if (typeof entry.status !== 'string' || entry.status === 'completed') continue
      entries.push({
        taskId: typeof entry.taskId === 'string' ? entry.taskId : undefined,
        agentId: typeof entry.agentId === 'string' ? entry.agentId : undefined,
        status: entry.status,
        error: typeof entry.error === 'string' ? entry.error : undefined,
      })
    }
  }
  return entries.map((entry) => ({
    taskId: entry.taskId!,
    agentId: entry.agentId,
    code: codeForTaskOutcome(entry.status, entry.error),
    message: entry.error ?? entry.status,
  }))
}

/** Completed task ids from the same report shapes (for Execution context). */
export function extractCompletedTaskIds(result: SupervisorRunResult): readonly string[] {
  const out: string[] = []
  const report = result.report.report as unknown as {
    readonly responses?: readonly Record<string, unknown>[]
    readonly steps?: readonly Record<string, unknown>[]
    readonly turns?: readonly Record<string, unknown>[]
  }
  for (const group of [report.responses, report.steps, report.turns]) {
    if (!Array.isArray(group)) continue
    for (const entry of group as Record<string, unknown>[]) {
      if (entry.status === 'completed' && typeof entry.taskId === 'string') out.push(entry.taskId)
    }
  }
  return out
}

/** Classify an error thrown by the Supervisor / planner layers. */
export function classifyThrown(error: unknown, attempt: number): FailureRecord {
  if (isSupervisorError(error)) {
    switch (error.kind) {
      case 'cancellation':
        return record('CANCELLED', error.message, attempt, { cause: error, thrown: true })
      case 'timeout':
        return record('TIMEOUT', error.message, attempt, { cause: error, thrown: true })
      case 'validation':
        return record('VALIDATION_ERROR', error.message, attempt, { cause: error, thrown: true })
      case 'execution':
      case 'aggregation':
        // Unknown runtime error: no automatic recovery without explicit evidence.
        return record('RUNTIME_ERROR', error.message, attempt, { cause: error, thrown: true })
    }
  }
  if (error instanceof PlanRoutingError) {
    return record('ROUTING_ERROR', error.message, attempt, {
      cause: error,
      thrown: true,
      ...(error.taskId !== undefined ? { taskId: error.taskId } : {}),
    })
  }
  if (error instanceof PlanValidationErrorPlanner || error instanceof PlanParseError) {
    return record('VALIDATION_ERROR', error.message, attempt, { cause: error, thrown: true })
  }
  if (error instanceof PlanIntegrationError) {
    return record('RUNTIME_ERROR', error.message, attempt, { cause: error, thrown: true })
  }
  if (error instanceof GraphError) {
    return record('RUNTIME_ERROR', error.message, attempt, { cause: error, thrown: true })
  }
  const message = error instanceof Error ? error.message : String(error)
  return record('RUNTIME_ERROR', message, attempt, { cause: error, thrown: true })
}

/** Classify a returned (non-throwing) Supervisor result with failures. */
export function classifyResult(result: SupervisorRunResult, attempt: number): FailureRecord {
  if (result.status === 'cancelled') {
    return record('CANCELLED', `run '${result.runId}' cancelled`, attempt, {
      taskFailures: extractTaskFailures(result),
    })
  }
  if (result.status === 'timeout') {
    return record('TIMEOUT', `run '${result.runId}' timed out`, attempt, {
      taskFailures: extractTaskFailures(result),
    })
  }
  const taskFailures = extractTaskFailures(result)
  let primary: FailureCode = 'TASK_ERROR'
  for (const candidate of PRIORITY) {
    if (taskFailures.some((failure) => failure.code === candidate)) {
      primary = candidate
      break
    }
  }
  const primaryRef = taskFailures.find((failure) => failure.code === primary)
  return record(primary, primaryRef?.message ?? `run '${result.runId}' failed`, attempt, {
    ...(primaryRef?.taskId !== undefined ? { taskId: primaryRef.taskId } : {}),
    ...(primaryRef?.agentId !== undefined ? { agentId: primaryRef.agentId } : {}),
    taskFailures,
  })
}
