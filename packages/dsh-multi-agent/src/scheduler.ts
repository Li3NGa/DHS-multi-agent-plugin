/**
 * Scheduler: executes a validated TaskGraph.
 *
 * TaskGraph -> ready tasks -> bounded parallel execution -> task executor
 * (AgentRunner over ctx.agents in the plugin wiring).
 */
import { TaskGraph } from './graph'
import { errorMessage, type TaskOutcome } from './runner'
import type { Task } from './task'
import { createRunId, emitEvent, type OrchestrationEvent, type OrchestrationObserver } from './telemetry'

/** Executes one task; resolves with an outcome instead of throwing. */
export type TaskExecute = (task: Task, signal: AbortSignal) => Promise<TaskOutcome>

export interface SchedulerOptions {
  /** Max tasks in flight; must be >= 1. */
  readonly concurrency?: number | undefined
  /** Optional synchronous observer. Observer failures never affect execution. */
  readonly observer?: OrchestrationObserver | undefined
}

export interface SchedulerReport {
  /** Insertion-ordered map of taskId -> final outcome for every task. */
  readonly results: ReadonlyMap<string, TaskOutcome>
  /** Completion order (may differ from insertion order). */
  readonly order: readonly string[]
  /** True when every task completed successfully. */
  readonly ok: boolean
  /** True when the run ended via stop()/AbortSignal. */
  readonly stopped: boolean
  /** Stable identifier for this scheduler invocation. */
  readonly runId: string
}

function safeEmit(observer: OrchestrationObserver | undefined, event: OrchestrationEvent): void {
  try { emitEvent(observer, event) } catch { /* telemetry must never break orchestration */ }
}

export class Scheduler {
  readonly #execute: TaskExecute
  readonly #concurrency: number
  readonly #observer: OrchestrationObserver | undefined
  #current: AbortController | undefined

  constructor(execute: TaskExecute, options: SchedulerOptions = {}) {
    this.#execute = execute
    this.#observer = options.observer
    const concurrency = options.concurrency
    if (concurrency !== undefined && (!Number.isInteger(concurrency) || concurrency < 1)) {
      throw new TypeError('concurrency must be an integer >= 1')
    }
    this.#concurrency = concurrency ?? Number.POSITIVE_INFINITY
  }

  /** Terminate the active run cooperatively (pending -> cancelled). */
  stop(): void {
    this.#current?.abort()
  }

  async run(graph: TaskGraph, signal?: AbortSignal): Promise<SchedulerReport> {
    if (this.#current !== undefined) throw new Error('Scheduler is already running')
    graph.validate()

    const runId = createRunId()
    const startedAt = Date.now()
    safeEmit(this.#observer, { kind: 'run.started', runId, timestamp: startedAt })

    const controller = new AbortController()
    this.#current = controller
    const forwardAbort = () => controller.abort()
    signal?.addEventListener('abort', forwardAbort, { once: true })
    if (signal?.aborted) controller.abort()

    const outcomes = new Map<string, TaskOutcome>()
    const order: string[] = []
    const running = new Set<string>()
    const busyAgents = new Set<string>()
    let wake: (() => void) | undefined

    controller.signal.addEventListener('abort', () => wake?.(), { once: true })

    const settle = (task: Task, outcome: TaskOutcome): void => {
      if (task.status !== 'running') {
        running.delete(task.id)
        busyAgents.delete(task.agentId)
        wake?.()
        return
      }
      task.status = outcome.status
      outcomes.set(task.id, outcome)
      order.push(task.id)
      running.delete(task.id)
      busyAgents.delete(task.agentId)
      const kind = outcome.status === 'completed' ? 'task.completed' : outcome.status === 'cancelled' ? 'task.cancelled' : 'task.failed'
      safeEmit(this.#observer, {
        kind,
        runId,
        timestamp: Date.now(),
        taskId: task.id,
        agentId: task.agentId,
        status: outcome.status,
        durationMs: outcome.durationMs,
        ...(outcome.error !== undefined ? { error: outcome.error } : {}),
      })
      wake?.()
    }

    const start = (task: Task): void => {
      task.status = 'running'
      running.add(task.id)
      busyAgents.add(task.agentId)
      safeEmit(this.#observer, {
        kind: 'task.started', runId, timestamp: Date.now(), taskId: task.id, agentId: task.agentId,
      })
      void this.#execute(task, controller.signal).then(
        (outcome) => settle(task, outcome),
        (error) => settle(task, {
          taskId: task.id, status: 'failed', text: undefined, error: errorMessage(error), durationMs: 0, raw: undefined,
        }),
      )
    }

    const cancelBlocked = (task: Task, reason: string): void => {
      task.status = 'cancelled'
      outcomes.set(task.id, { taskId: task.id, status: 'cancelled', text: undefined, error: reason, durationMs: 0, raw: undefined })
      order.push(task.id)
      safeEmit(this.#observer, {
        kind: 'task.blocked', runId, timestamp: Date.now(), taskId: task.id, agentId: task.agentId, status: 'cancelled', error: reason,
      })
    }

    let stopped = false
    const stoppedNow = (): boolean => {
      if (stopped) return true
      if (controller.signal.aborted) { stopped = true; return true }
      return false
    }

    try {
      for (;;) {
        for (const task of graph.tasks()) {
          if (task.status !== 'pending') continue
          for (const dep of task.dependsOn) {
            const depTask = graph.get(dep)
            if (depTask !== undefined && depTask.isTerminal && depTask.status !== 'completed') {
              cancelBlocked(task, `dependency '${dep}' ${depTask.status}`)
              break
            }
          }
        }

        if (!stoppedNow()) {
          for (const task of graph.ready()) {
            if (running.size >= this.#concurrency) break
            if (busyAgents.has(task.agentId)) continue
            task.status = 'ready'
            start(task)
          }
        }

        if (running.size === 0) {
          if (graph.isComplete()) break
          if (stoppedNow()) break
          const stuck = graph.tasks().filter((task) => !task.isTerminal).map((task) => task.id)
          throw new Error(`scheduler stalled on non-terminal tasks: ${stuck.join(', ')}`)
        }
        if (stoppedNow()) break
        await new Promise<void>((resolve) => { wake = resolve })
      }

      if (stopped) {
        for (const task of graph.tasks()) {
          if (task.isTerminal) continue
          const wasRunning = task.status === 'running'
          cancelBlocked(task, 'cancelled (run stopped)')
          running.delete(task.id)
          if (wasRunning) busyAgents.delete(task.agentId)
        }
      }
    } finally {
      signal?.removeEventListener('abort', forwardAbort)
      this.#current = undefined
    }

    const wasStopped = stopped || controller.signal.aborted
    const results = new Map<string, TaskOutcome>()
    let ok = true
    for (const task of graph.tasks()) {
      const outcome = outcomes.get(task.id)
      results.set(task.id, outcome as TaskOutcome)
      if (outcome?.status !== 'completed') ok = false
    }
    safeEmit(this.#observer, { kind: 'run.completed', runId, timestamp: Date.now(), durationMs: Date.now() - startedAt, status: ok ? 'completed' : wasStopped ? 'cancelled' : 'failed' })
    return { results, order: [...order], ok, stopped: wasStopped, runId }
  }
}
