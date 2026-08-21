/**
 * Task: one unit of agent work inside an orchestrated run.
 *
 * A Task carries only data and its lifecycle status. It never touches the
 * agent loop, the LLM, the session or any provider - those live behind
 * {@link import('./runner').AgentRunner}. Status transitions are owned by
 * the TaskGraph / Scheduler (pending -> ready -> running -> terminal).
 */

export type TaskStatus =
  | 'pending'
  | 'ready'
  | 'running'
  | 'completed'
  | 'failed'
  | 'cancelled'

const TERMINAL_STATUSES: ReadonlySet<TaskStatus> = new Set([
  'completed',
  'failed',
  'cancelled',
])

export function isTerminalStatus(status: TaskStatus): boolean {
  return TERMINAL_STATUSES.has(status)
}

export interface TaskMetadata {
  readonly [key: string]: unknown
}

export interface TaskSpec {
  readonly id: string
  readonly agentId: string
  readonly prompt: string
  readonly dependsOn?: readonly string[] | undefined
  readonly timeoutMs?: number | undefined
  readonly metadata?: TaskMetadata | undefined
}

function assertNonEmptyString(value: unknown, field: string): void {
  if (typeof value !== 'string' || value.length === 0) {
    throw new TypeError(`Task ${field} must be a non-empty string`)
  }
}

export class Task {
  readonly id: string
  readonly agentId: string
  readonly prompt: string
  readonly dependsOn: readonly string[]
  readonly timeoutMs: number | undefined
  readonly metadata: TaskMetadata

  /** Lifecycle status; transitions are owned by TaskGraph / Scheduler. */
  status: TaskStatus = 'pending'

  constructor(spec: TaskSpec) {
    assertNonEmptyString(spec.id, 'id')
    assertNonEmptyString(spec.agentId, 'agentId')
    if (typeof spec.prompt !== 'string') {
      throw new TypeError('Task prompt must be a string')
    }
    if (spec.timeoutMs !== undefined) {
      if (typeof spec.timeoutMs !== 'number' || !Number.isFinite(spec.timeoutMs) || spec.timeoutMs <= 0) {
        throw new TypeError('Task timeoutMs must be a finite number > 0')
      }
    }
    const dependsOn = spec.dependsOn ?? []
    if (!Array.isArray(dependsOn)) {
      throw new TypeError('Task dependsOn must be an array of task ids')
    }
    const seen = new Set<string>()
    for (const dep of dependsOn) {
      assertNonEmptyString(dep, 'dependency id')
      if (seen.has(dep)) {
        throw new TypeError(`Task '${spec.id}' lists dependency '${dep}' more than once`)
      }
      seen.add(dep)
    }
    this.id = spec.id
    this.agentId = spec.agentId
    this.prompt = spec.prompt
    this.dependsOn = [...dependsOn]
    this.timeoutMs = spec.timeoutMs
    this.metadata = Object.freeze({ ...spec.metadata })
  }

  get isTerminal(): boolean {
    return isTerminalStatus(this.status)
  }

  /**
   * Copy with a different prompt, keeping id / dependencies / options.
   * Used by strategies that resolve the final prompt at execution time
   * (Sequential, Relay); identity stays the same task for the scheduler.
   */
  withPrompt(prompt: string): Task {
    return new Task({
      id: this.id,
      agentId: this.agentId,
      prompt,
      dependsOn: this.dependsOn,
      timeoutMs: this.timeoutMs,
      metadata: this.metadata,
    })
  }
}
