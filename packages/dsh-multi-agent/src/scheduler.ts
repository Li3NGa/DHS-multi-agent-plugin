/**
 * Scheduler: executes a validated TaskGraph.
 *
 * TaskGraph -> ready tasks -> bounded parallel execution -> task executor
 * (AgentRunner over ctx.agents in the plugin wiring).
 *
 * Behaviour (ported from the verified Python reference, not its
 * implementation details):
 * - dependency ordering: a task starts only after all deps completed
 * - failure propagation: a failed/cancelled/timeout dep cancels every
 *   dependent (outcome `cancelled`, error names the dependency)
 * - configurable concurrency (default unlimited; launch order is graph
 *   insertion order)
 * - per-agent serialization: at most one task for a given `agentId` is in
 *   flight at a time. DSH agents own a single live turn/session stream;
 *   allowing concurrent followups on one agent would make session-event
 *   correlation ambiguous and can merge two task outputs. Different agents
 *   may still execute in parallel up to the global concurrency limit.
 * - deterministic result ordering: the returned map iterates in graph
 *   insertion order regardless of completion order; `order` records the
 *   actual completion sequence
 * - cancellation: AbortSignal or stop() cancel pending tasks immediately;
 *   in-flight tasks are marked cancelled and their late results dropped
 *   (promises cannot be killed - cooperative model)
 * - termination: the run resolves when every task is terminal; no task
 *   remains unaccounted
 * - no sleeps and no random delays anywhere: the loop is woken strictly
 *   by task completions / cancellation
 */
import { TaskGraph } from './graph'
import { errorMessage, type TaskOutcome } from './runner'
import type { Task } from './task'

/** Executes one task; resolves with an outcome instead of throwing. */
export type TaskExecute = (task: Task, signal: AbortSignal) => Promise<TaskOutcome>

export interface SchedulerOptions {
  /** Max tasks in flight; must be >= 1. */
  readonly concurrency?: number | undefined
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
}

export class Scheduler {
  readonly #execute: TaskExecute
  readonly #concurrency: number
  #current: AbortController | undefined

  constructor(execute: TaskExecute, options: SchedulerOptions = {}) {
    this.#execute = execute
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
    if (this.#current !== undefined) {
      throw new Error('Scheduler is already running')
    }
    graph.validate()

    const nonPending = graph.tasks().filter((task) => task.status !== 'pending')
    if (nonPending.length > 0) {
      const details = nonPending
        .map((task) => `${task.id}=${task.status}`)
        .join(', ')
      throw new Error(`TaskGraph cannot be reused after scheduling; non-pending tasks: ${details}`)
    }

    const controller = new AbortController()
    this.#current = controller
    const forwardAbort = () => controller.abort()
    signal?.addEventListener('abort', forwardAbort, { once: true })
    // an already-aborted signal never fires the listener
    if (signal?.aborted) controller.abort()

    const outcomes = new Map<string, TaskOutcome>()
    const order: string[] = []
    const running = new Set<string>()
    const busyAgents = new Set<string>()
    let wake: (() => void) | undefined

    controller.signal.addEventListener(
      'abort',
      () => wake?.(),
      { once: true },
    )

    const settle = (task: Task, outcome: TaskOutcome): void => {
      // a task cancelled by stop() while in flight drops its late result
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
      wake?.()
    }

    const start = (task: Task): void => {
      task.status = 'running'
      running.add(task.id)
      busyAgents.add(task.agentId)
      void this.#execute(task, controller.signal).then(
        (outcome) => settle(task, outcome),
        (error) =>
          settle(task, {
            taskId: task.id,
            status: 'failed',
            text: undefined,
            error: errorMessage(error),
            durationMs: 0,
            raw: undefined,
          }),
      )
    }

    const cancelBlocked = (task: Task, reason: string): void => {
      task.status = 'cancelled'
      outcomes.set(task.id, {
        taskId: task.id,
        status: 'cancelled',
        text: undefined,
        error: reason,
        durationMs: 0,
        raw: undefined,
      })
      order.push(task.id)
    }

    let stopped = false
    const stoppedNow = (): boolean => {
      if (stopped) return true
      if (controller.signal.aborted) {
        stopped = true
        return true
      }
      return false
    }

    try {
      for (;;) {
        // 1) cancel tasks whose dependencies did not succeed
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

        // 2) launch ready tasks in insertion order, bounded by concurrency.
        // Tasks sharing an agent are treated as a single execution slot;
        // tasks targeting other agents remain eligible for parallel launch.
        if (!stoppedNow()) {
          for (const task of graph.ready()) {
            if (running.size >= this.#concurrency) break
            if (busyAgents.has(task.agentId)) continue
            task.status = 'ready'
            start(task)
          }
        }

        // 3) termination / stall checks
        if (running.size === 0) {
          if (graph.isComplete()) break
          if (stoppedNow()) break
          // post-validate this means statuses are inconsistent (a bug),
          // because every non-terminal task is either ready or blocked
          const stuck = graph.tasks().filter((task) => !task.isTerminal).map((task) => task.id)
          throw new Error(`scheduler stalled on non-terminal tasks: ${stuck.join(', ')}`)
        }
        if (stoppedNow()) break

        // 4) wait for the next completion / cancellation event
        await new Promise<void>((resolve) => {
          wake = resolve
        })
      }

      // 5) cooperative teardown for stop(): everything not terminal yet
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

    // deterministic ordering: graph insertion order for the results map
    const wasStopped = stopped || controller.signal.aborted
    const results = new Map<string, TaskOutcome>()
    let ok = true
    for (const task of graph.tasks()) {
      const outcome = outcomes.get(task.id)
      // every task is terminal here, so an outcome must exist
      results.set(task.id, outcome as TaskOutcome)
      if (outcome?.status !== 'completed') ok = false
    }
    return { results, order: [...order], ok, stopped: wasStopped }
  }
}
