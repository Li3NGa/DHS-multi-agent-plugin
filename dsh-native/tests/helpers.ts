import type { TaskExecute } from '../src/scheduler'
import type { TaskOutcome } from '../src/runner'
import type { Task } from '../src/task'

export interface Deferred<T> {
  readonly promise: Promise<T>
  resolve(value: T): void
  reject(error: unknown): void
}

export function deferred<T = void>(): Deferred<T> {
  let resolve!: (value: T) => void
  let reject!: (error: unknown) => void
  const promise = new Promise<T>((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

export function okOutcome(taskId: string, text = `${taskId}-out`): TaskOutcome {
  return {
    taskId,
    status: 'completed',
    text,
    error: undefined,
    durationMs: 1,
    raw: undefined,
  }
}

export function failOutcome(taskId: string, error = `${taskId}-boom`): TaskOutcome {
  return { taskId, status: 'failed', text: undefined, error, durationMs: 1, raw: undefined }
}

/** Execute fn that records every call and defers completion per task. */
export function scriptedExecute(
  script: (task: Task) => 'ok' | 'fail' | 'hang' | Promise<'ok' | 'fail' | 'hang'>,
): {
  execute: TaskExecute
  calls: Task[]
  gates: Map<string, Deferred<void>>
} {
  const calls: Task[] = []
  const gates = new Map<string, Deferred<void>>()
  const execute: TaskExecute = async (task) => {
    calls.push(task)
    const gate = deferred<void>()
    gates.set(task.id, gate)
    const behavior = await script(task)
    if (behavior === 'hang') {
      await gate.promise
      return okOutcome(task.id, `${task.id}-late`)
    }
    return behavior === 'ok' ? okOutcome(task.id) : failOutcome(task.id)
  }
  return { execute, calls, gates }
}
