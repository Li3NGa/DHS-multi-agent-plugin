/**
 * TaskGraph: a strict DAG of Tasks.
 *
 * Structural problems are detected loudly, never repaired silently:
 * duplicate ids are rejected by add(); missing dependencies, self
 * dependencies and cycles are rejected by validate(). The scheduler runs
 * validate() before executing anything, so a graph either executes as
 * declared or does not execute at all.
 *
 * Query methods are deterministic: tasks keep insertion order.
 */
import { Task, type TaskSpec, isTerminalStatus } from './task'

export type GraphErrorCode =
  | 'duplicate-id'
  | 'unknown-task'
  | 'missing-dependency'
  | 'self-dependency'
  | 'cycle'

export class GraphError extends Error {
  readonly code: GraphErrorCode

  constructor(code: GraphErrorCode, message: string) {
    super(message)
    this.name = 'GraphError'
    this.code = code
  }
}

export class TaskGraph {
  readonly #tasks = new Map<string, Task>()

  /** Add a task; duplicate ids are rejected immediately. */
  add(spec: TaskSpec | Task): Task {
    const task = spec instanceof Task ? spec : new Task(spec)
    if (this.#tasks.has(task.id)) {
      throw new GraphError('duplicate-id', `duplicate task id: '${task.id}'`)
    }
    this.#tasks.set(task.id, task)
    return task
  }

  get(id: string): Task | undefined {
    return this.#tasks.get(id)
  }

  has(id: string): boolean {
    return this.#tasks.has(id)
  }

  get size(): number {
    return this.#tasks.size
  }

  /** All tasks in insertion order. */
  tasks(): readonly Task[] {
    return [...this.#tasks.values()]
  }

  /** Dependencies of a task, in declaration order. */
  dependencies(id: string): readonly string[] {
    const task = this.#tasks.get(id)
    if (!task) throw new GraphError('unknown-task', `unknown task: '${id}'`)
    return task.dependsOn
  }

  /** Direct dependents of a task, in insertion order. */
  dependents(id: string): readonly string[] {
    if (!this.#tasks.has(id)) throw new GraphError('unknown-task', `unknown task: '${id}'`)
    const out: string[] = []
    for (const task of this.#tasks.values()) {
      if (task.dependsOn.includes(id)) out.push(task.id)
    }
    return out
  }

  /**
   * Tasks that may start now: still pending and every dependency
   * completed. Insertion order; statuses 'ready'/'running' are excluded
   * because they already left the pending pool.
   */
  ready(): readonly Task[] {
    const ready: Task[] = []
    for (const task of this.#tasks.values()) {
      if (task.status !== 'pending') continue
      if (this.#depsCompleted(task)) ready.push(task)
    }
    return ready
  }

  /** True when no task can ever change status again (all terminal). */
  isComplete(): boolean {
    for (const task of this.#tasks.values()) {
      if (!task.isTerminal) return false
    }
    return true
  }

  /**
   * Reject missing dependencies, self dependencies and cycles, naming the
   * offending tasks. Never drops or rewrites edges to make a graph valid.
   */
  validate(): void {
    for (const task of this.#tasks.values()) {
      for (const dep of task.dependsOn) {
        if (dep === task.id) {
          throw new GraphError('self-dependency', `task '${task.id}' depends on itself`)
        }
        if (!this.#tasks.has(dep)) {
          throw new GraphError(
            'missing-dependency',
            `task '${task.id}' depends on unknown task '${dep}'`,
          )
        }
      }
    }
    const cycle = this.#findCycle()
    if (cycle) {
      throw new GraphError('cycle', `dependency cycle detected: ${cycle.join(' -> ')}`)
    }
  }

  #depsCompleted(task: Task): boolean {
    for (const dep of task.dependsOn) {
      const depTask = this.#tasks.get(dep)
      if (!depTask || depTask.status !== 'completed') return false
    }
    return true
  }

  /**
   * Iterative DFS cycle search over declaration order; returns one cycle
   * as a path (a -> b -> a) or undefined when the graph is acyclic.
   */
  #findCycle(): readonly string[] | undefined {
    const WHITE = 0
    const GRAY = 1
    const BLACK = 2
    const color = new Map<string, number>()
    for (const id of this.#tasks.keys()) color.set(id, WHITE)

    for (const root of this.#tasks.keys()) {
      if (color.get(root) !== WHITE) continue
      const stack: { id: string; iter: number }[] = [{ id: root, iter: 0 }]
      const path: string[] = []
      color.set(root, GRAY)
      path.push(root)
      while (stack.length > 0) {
        const frame = stack[stack.length - 1]!
        const deps = this.#tasks.get(frame.id)!.dependsOn
        if (frame.iter < deps.length) {
          const dep = deps[frame.iter]!
          frame.iter += 1
          if (dep === frame.id) continue // self-dep reported separately
          const depColor = color.get(dep) ?? BLACK
          if (depColor === GRAY) {
            const start = path.indexOf(dep)
            return [...path.slice(start === -1 ? 0 : start), dep]
          }
          if (depColor === WHITE) {
            color.set(dep, GRAY)
            path.push(dep)
            stack.push({ id: dep, iter: 0 })
          }
        } else {
          color.set(frame.id, BLACK)
          path.pop()
          stack.pop()
        }
      }
    }
    return undefined
  }
}

export { isTerminalStatus }
