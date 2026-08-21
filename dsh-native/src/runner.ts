/**
 * AgentRunner: executes one Task against ctx.agents.
 *
 * Responsibilities (and nothing else):
 * - resolve the task's agent (`missing agent` is a failed task, not a throw)
 * - await `followup()` and, when available, `whenIdle()` (tool draining)
 * - enforce the task timeout cooperatively (see below)
 * - propagate AbortSignal cancellation
 * - normalize the reply (string / {content} / {text} / event list) to text
 *
 * Cooperative timeout & cancellation: JavaScript promises cannot be
 * killed. When the timeout fires or the run is cancelled, the runner
 * settles the task outcome immediately; the underlying followup promise
 * is kept alive but ignored (its rejection is swallowed on purpose).
 * This mirrors the verified behaviour of the Python reference runtime.
 */
import type { DshContext } from './dsh'
import type { Task } from './task'

export type TaskOutcomeStatus = 'completed' | 'failed' | 'cancelled'

export interface TaskOutcome {
  readonly taskId: string
  readonly status: TaskOutcomeStatus
  readonly text: string | undefined
  readonly error: string | undefined
  readonly durationMs: number
  readonly raw: unknown
}

export interface AgentRunnerOptions {
  /** Timeout used when a Task carries no timeoutMs of its own. */
  readonly defaultTimeoutMs?: number | undefined
}

type RaceReason = 'timeout' | 'aborted'

type RaceResult = { readonly ok: true; readonly value: unknown } | { readonly ok: false; readonly reason: RaceReason }

export class AgentRunner {
  readonly #agents: DshContext['agents']
  readonly #defaultTimeoutMs: number | undefined

  constructor(ctx: DshContext, options: AgentRunnerOptions = {}) {
    this.#agents = ctx.agents
    this.#defaultTimeoutMs = options.defaultTimeoutMs
  }

  async run(task: Task, signal?: AbortSignal): Promise<TaskOutcome> {
    const startedAt = Date.now()
    const done = (
      status: TaskOutcomeStatus,
      text?: string,
      error?: string,
      raw?: unknown,
    ): TaskOutcome => ({
      taskId: task.id,
      status,
      text,
      error,
      durationMs: Date.now() - startedAt,
      raw,
    })

    if (signal?.aborted) {
      return done('cancelled', undefined, 'cancelled before start')
    }

    const agent = this.#agents.get(task.agentId)
    if (!agent) {
      return done('failed', undefined, `agent '${task.agentId}' not found`)
    }

    const timeoutMs = task.timeoutMs ?? this.#defaultTimeoutMs
    let timer: ReturnType<typeof setTimeout> | undefined
    let onAbort: (() => void) | undefined
    const execution = (async () => {
      const reply = await agent.followup(task.prompt)
      if (typeof agent.whenIdle === 'function') {
        await agent.whenIdle()
      }
      return reply
    })()

    const race = new Promise<RaceResult>((resolve) => {
      if (timeoutMs !== undefined) {
        timer = setTimeout(() => resolve({ ok: false, reason: 'timeout' }), timeoutMs)
      }
      if (signal) {
        onAbort = () => resolve({ ok: false, reason: 'aborted' })
        signal.addEventListener('abort', onAbort, { once: true })
      }
    })
    // when the race decides first, the still-running followup must not
    // surface as an unhandled rejection
    execution.catch(() => {})

    try {
      const settled = await Promise.race([execution.then((value): RaceResult => ({ ok: true, value })), race])
      if (!settled.ok && settled.reason === 'timeout') {
        return done('failed', undefined, `timeout after ${timeoutMs}ms`)
      }
      if (!settled.ok && settled.reason === 'aborted') {
        return done('cancelled', undefined, 'cancelled')
      }
      if (settled.ok) {
        const text = normalizeReply(settled.value)
        return done('completed', text, undefined, settled.value)
      }
      return done('failed', undefined, 'unreachable race result', undefined)
    } catch (error) {
      return done('failed', undefined, errorMessage(error), undefined)
    } finally {
      if (timer !== undefined) clearTimeout(timer)
      if (signal && onAbort !== undefined) signal.removeEventListener('abort', onAbort)
    }
  }
}

/**
 * Flatten the reply shapes observed on the DSH result channel:
 * - plain string
 * - `{ content }` / `{ text }` objects
 * - arrays (session events): assistant-ish entries are joined with a
 *   blank line, in event order; non-assistant entries are skipped
 *
 * Adjust this single function when the real DSH event types are wired in.
 */
export function normalizeReply(reply: unknown): string {
  if (typeof reply === 'string') return reply
  if (isReplyObject(reply)) {
    const value = reply.content ?? reply.text
    return value === undefined ? String(reply) : normalizeReply(value)
  }
  if (Array.isArray(reply)) {
    const parts: string[] = []
    for (const item of reply) {
      const text = extractAssistantText(item)
      if (text !== undefined) parts.push(text)
    }
    if (parts.length > 0) return parts.join('\n\n')
    return String(reply)
  }
  return String(reply)
}

function isReplyObject(value: unknown): value is { content?: unknown; text?: unknown } {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

/**
 * Best-effort assistant-event detection for event lists. Recognizes the
 * common shapes without assuming exact DSH event types:
 * `{ role: 'assistant', content }`, `{ type: 'assistant', text }`,
 * `{ content: string }`, plain strings.
 */
function extractAssistantText(item: unknown): string | undefined {
  if (typeof item === 'string') return item
  if (!isReplyObject(item)) return undefined
  const role = (item as { role?: unknown }).role
  const type = (item as { type?: unknown }).type
  const isAssistant =
    role === 'assistant' || type === 'assistant' ||
    (role === undefined && type === undefined)
  if (!isAssistant) return undefined
  const content = (item as { content?: unknown; text?: unknown }).content
  const text = (item as { text?: unknown }).text
  const value = content ?? text
  if (typeof value === 'string') return value
  return undefined
}

export function errorMessage(error: unknown): string {
  if (error instanceof Error) return error.message
  return String(error)
}
