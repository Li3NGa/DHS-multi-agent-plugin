/**
 * Low-overhead, privacy-preserving runtime observability.
 *
 * Events deliberately contain identifiers, statuses, counters and timings only.
 * Prompts, assistant text, tool payloads and raw DSH session events never cross
 * this boundary. Observer failures are isolated from task execution.
 */
import type { FailureCode, RecoveryDecision, RecoveryRunResult } from './recovery'
import type { TaskOutcome } from './runner'
import type { Task } from './task'

export type ObservabilityEvent =
  | {
      readonly type: 'task.started'
      readonly at: string
      readonly taskId: string
      readonly agentId: string
    }
  | {
      readonly type: 'task.finished'
      readonly at: string
      readonly taskId: string
      readonly agentId: string
      readonly status: TaskOutcome['status']
      readonly durationMs: number
    }
  | {
      readonly type: 'recovery.started'
      readonly at: string
      readonly runId: string
      readonly planId: string
    }
  | {
      readonly type: 'recovery.attempt'
      readonly at: string
      readonly runId: string
      readonly attempt: number
    }
  | {
      readonly type: 'recovery.failure'
      readonly at: string
      readonly runId: string
      readonly attempt: number
      readonly code: FailureCode
      readonly taskId: string | undefined
      readonly agentId: string | undefined
    }
  | {
      readonly type: 'recovery.decision'
      readonly at: string
      readonly runId: string
      readonly attempt: number
      readonly decision: RecoveryDecision
    }
  | {
      readonly type: 'recovery.finished'
      readonly at: string
      readonly runId: string
      readonly status: RecoveryRunResult['status']
      readonly attempts: number
      readonly repairsUsed: number
      readonly replansUsed: number
      readonly durationMs: number
    }

export type RuntimeObserver = (event: ObservabilityEvent) => void

export interface MetricsSnapshot {
  readonly tasksStarted: number
  readonly tasksCompleted: number
  readonly tasksFailed: number
  readonly tasksCancelled: number
  readonly recoveryRuns: number
  readonly recoveryCompleted: number
  readonly recoveryFailed: number
  readonly recoveryCancelled: number
  readonly recoveryTimeouts: number
  readonly recoveryAttempts: number
  readonly repairs: number
  readonly replans: number
  readonly failuresByCode: Readonly<Record<FailureCode, number>>
  readonly decisions: Readonly<Record<RecoveryDecision, number>>
}

const FAILURE_CODES: readonly FailureCode[] = [
  'VALIDATION_ERROR',
  'ROUTING_ERROR',
  'TASK_ERROR',
  'TIMEOUT',
  'CANCELLED',
  'DEPENDENCY_FAILURE',
  'AGENT_UNAVAILABLE',
  'STRATEGY_ERROR',
  'RUNTIME_ERROR',
]

const DECISIONS: readonly RecoveryDecision[] = [
  'retry',
  'repair',
  'replan',
  'abort',
  'completed',
  'failed',
]

function emptyCounts<T extends string>(keys: readonly T[]): Record<T, number> {
  return Object.fromEntries(keys.map((key) => [key, 0])) as Record<T, number>
}

/** In-memory metrics collector suitable for dashboards or periodic export. */
export class MetricsCollector {
  readonly #failuresByCode = emptyCounts(FAILURE_CODES)
  readonly #decisions = emptyCounts(DECISIONS)
  #tasksStarted = 0
  #tasksCompleted = 0
  #tasksFailed = 0
  #tasksCancelled = 0
  #recoveryRuns = 0
  #recoveryCompleted = 0
  #recoveryFailed = 0
  #recoveryCancelled = 0
  #recoveryTimeouts = 0
  #recoveryAttempts = 0
  #repairs = 0
  #replans = 0

  readonly observer: RuntimeObserver = (event) => this.record(event)

  record(event: ObservabilityEvent): void {
    switch (event.type) {
      case 'task.started':
        this.#tasksStarted += 1
        return
      case 'task.finished':
        if (event.status === 'completed') this.#tasksCompleted += 1
        else if (event.status === 'failed') this.#tasksFailed += 1
        else this.#tasksCancelled += 1
        return
      case 'recovery.started':
        this.#recoveryRuns += 1
        return
      case 'recovery.attempt':
        this.#recoveryAttempts += 1
        return
      case 'recovery.failure':
        this.#failuresByCode[event.code] += 1
        return
      case 'recovery.decision':
        this.#decisions[event.decision] += 1
        if (event.decision === 'repair') this.#repairs += 1
        if (event.decision === 'replan') this.#replans += 1
        return
      case 'recovery.finished':
        if (event.status === 'completed') this.#recoveryCompleted += 1
        else if (event.status === 'cancelled') this.#recoveryCancelled += 1
        else if (event.status === 'timeout') this.#recoveryTimeouts += 1
        else this.#recoveryFailed += 1
        return
    }
  }

  snapshot(): MetricsSnapshot {
    return {
      tasksStarted: this.#tasksStarted,
      tasksCompleted: this.#tasksCompleted,
      tasksFailed: this.#tasksFailed,
      tasksCancelled: this.#tasksCancelled,
      recoveryRuns: this.#recoveryRuns,
      recoveryCompleted: this.#recoveryCompleted,
      recoveryFailed: this.#recoveryFailed,
      recoveryCancelled: this.#recoveryCancelled,
      recoveryTimeouts: this.#recoveryTimeouts,
      recoveryAttempts: this.#recoveryAttempts,
      repairs: this.#repairs,
      replans: this.#replans,
      failuresByCode: { ...this.#failuresByCode },
      decisions: { ...this.#decisions },
    }
  }

  reset(): void {
    for (const code of FAILURE_CODES) this.#failuresByCode[code] = 0
    for (const decision of DECISIONS) this.#decisions[decision] = 0
    this.#tasksStarted = 0
    this.#tasksCompleted = 0
    this.#tasksFailed = 0
    this.#tasksCancelled = 0
    this.#recoveryRuns = 0
    this.#recoveryCompleted = 0
    this.#recoveryFailed = 0
    this.#recoveryCancelled = 0
    this.#recoveryTimeouts = 0
    this.#recoveryAttempts = 0
    this.#repairs = 0
    this.#replans = 0
  }
}

export function createMetricsCollector(): MetricsCollector {
  return new MetricsCollector()
}

/** Observer errors must never change runtime semantics. */
export function observe(observer: RuntimeObserver | undefined, event: ObservabilityEvent): void {
  if (observer === undefined) return
  try {
    observer(event)
  } catch {
    // Observability is best-effort by contract.
  }
}

export function taskStarted(task: Task): ObservabilityEvent {
  return { type: 'task.started', at: new Date().toISOString(), taskId: task.id, agentId: task.agentId }
}

export function taskFinished(task: Task, outcome: TaskOutcome): ObservabilityEvent {
  return {
    type: 'task.finished',
    at: new Date().toISOString(),
    taskId: task.id,
    agentId: task.agentId,
    status: outcome.status,
    durationMs: outcome.durationMs,
  }
}
