/**
 * Unified Strategy Contract (Phase D).
 *
 * Every strategy report carries this envelope so a future Supervisor can
 * consume ANY strategy through one shape without knowing its internals.
 * The envelope reuses the frozen Runtime models — statuses are the
 * AgentRunner's TaskOutcomeStatus, task correlation stays the Scheduler's
 * taskId insertion order; nothing here introduces a second result model
 * or its own timeout/cancellation (all lifecycle control flows through
 * the Runtime API frozen in Phase C).
 *
 * Run-level status derivation (frozen):
 *   stopped  -> 'cancelled'   (run ended via stop()/AbortSignal)
 *   otherwise all tasks completed            -> 'success'
 *   otherwise at least one task completed    -> 'partial'
 *   otherwise                                -> 'failed'
 * Task-level timeouts surface as failed entries whose error starts with
 * 'timeout:' (Runner semantics); metadata.timedOut counts them.
 */
import type { TaskOutcomeStatus } from '../runner'

export type StrategyKind = 'broadcast' | 'sequential' | 'relay'

export type StrategyRunStatus = 'success' | 'partial' | 'failed' | 'cancelled'

/** Uniform per-task view; correlation is the Scheduler's taskId. */
export interface StrategyTask {
  readonly taskId: string
  readonly agentId: string
  readonly status: TaskOutcomeStatus
  readonly text: string | undefined
  readonly error: string | undefined
}

export interface StrategyError {
  readonly taskId: string
  readonly error: string
}

export interface StrategyMetadata {
  readonly taskCount: number
  readonly completed: number
  readonly failed: number
  readonly cancelled: number
  readonly timedOut: number
}

/**
 * Common envelope satisfied by BroadcastReport / SequentialReport /
 * RelayReport. Strategy-specific fields (steps / turns / responses /
 * final / draft / joined) extend it and stay internal to consumers that
 * opt into them.
 */
export interface StrategyReport {
  readonly strategy: StrategyKind
  readonly status: StrategyRunStatus
  /** True exactly when status is 'success'. */
  readonly ok: boolean
  /** True when the run ended via stop()/AbortSignal (Scheduler semantics). */
  readonly stopped: boolean
  /** One entry per task, declaration order. */
  readonly tasks: readonly StrategyTask[]
  /** Completed texts, declaration order. */
  readonly outputs: readonly string[]
  /** Non-success entries with their per-task error, declaration order. */
  readonly errors: readonly StrategyError[]
  readonly metadata: StrategyMetadata
}

const TIMEOUT_ERROR_PREFIX = 'timeout'

/** Derive the envelope from the uniform task view (pure). */
export function strategyEnvelope(
  strategy: StrategyKind,
  stopped: boolean,
  tasks: readonly StrategyTask[],
): StrategyReport {
  let completed = 0
  let failed = 0
  let cancelled = 0
  let timedOut = 0
  const outputs: string[] = []
  const errors: StrategyError[] = []
  for (const task of tasks) {
    if (task.status === 'completed') {
      completed += 1
      if (task.text !== undefined) outputs.push(task.text)
    } else {
      errors.push({ taskId: task.taskId, error: task.error ?? task.status })
      if (task.status === 'failed') {
        failed += 1
        if (task.error?.startsWith(TIMEOUT_ERROR_PREFIX) === true) timedOut += 1
      } else {
        cancelled += 1
      }
    }
  }
  const status: StrategyRunStatus = stopped
    ? 'cancelled'
    : completed === tasks.length
      ? 'success'
      : completed > 0
        ? 'partial'
        : 'failed'
  return {
    strategy,
    status,
    ok: status === 'success',
    stopped,
    tasks,
    outputs,
    errors,
    metadata: { taskCount: tasks.length, completed, failed, cancelled, timedOut },
  }
}
