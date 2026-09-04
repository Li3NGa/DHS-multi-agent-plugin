import { TaskGraph } from './graph'
import { errorMessage, type TaskOutcome } from './runner'
import type { Task } from './task'

export type TaskExecute = (task: Task, signal: AbortSignal) => Promise<TaskOutcome>

export interface SchedulerOptions {
  readonly concurrency?: number | undefined
}

export interface SchedulerReport {
  readonly results: ReadonlyMap<string, TaskOutcome>
  readonly order: readonly string[]
  readonly ok: boolean
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

  stop(): void {
    this.#current?.abort()
  }

  async run(graph: TaskGraph, signal?: AbortSignal): Promise<SchedulerReport> {
    if (this.#current !== undefined) throw new Error('Scheduler is already running')
    graph.validate()

    const nonPending = graph.tasks().filter((task) => task.status !== 'pending')
    if (nonPending.length > 0) {
      const details = nonPending.map((task) => `${task.id}=${task.status}`).join(', ')
      throw new Error(`TaskGraph cannot be reused after scheduling; non-pending tasks: ${details}`)
    }

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
      wake?.()
    }

    const start = (task: Task): void => {
      task.status = 'running'
      running.add(task.id)
      busyAgents.add(task.agentId)
      void this.#execute(task, controller.signal).then(
        (outcome) => settle(task, outcome),
        (error) => settle(task, {
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
      if (!controller.signal.aborted) return false
      stopped = true
      return true
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

        await new Promise<void>((resolve) => {
          wake = resolve
        })
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
    return { results, order: [...order], ok, stopped: wasStopped }
  }
}
