/**
 * AgentRunner: executes one Task against the real DSH agent API.
 *
 * Flow per task (all DSH-side state transitions are driven by the real
 * harness, not re-implemented here):
 *
 *   baseline = agent.session.events.length        // correlation boundary
 *   agent.followup(userMessage)                   // void; opens its own turn
 *   await agent.whenIdle()                        // raced against timeout/signal
 *   events = agent.session.events.slice(baseline) // exactly this task's turn
 *
 * The outcome is derived from the sliced session events:
 * - `assistant/message` events -> text (text blocks joined; usage-only
 *   empty-content messages skipped; an `interrupted: true` prefix is kept
 *   as partial text for cancelled/timed-out turns)
 * - `turn/end` reason: completed -> completed; aborted via AbortSignal ->
 *   cancelled; aborted via timeout -> failed("timeout ..."); error ->
 *   failed(turn error); blocked / max-tokens / interrupted -> failed
 * - `tool/call` / `tool/result` counts are exposed on `raw`
 *
 * Timeout / cancellation use the HOST mechanism: `agent.cancel({ kind:
 * 'hook', reason })` aborts the live turn and `whenIdle()` converges, so
 * nothing is left hanging on the agent. The remaining cooperative boundary
 * is documented in the plugin README: if the harness itself never converges
 * after cancel, a bounded grace window (max(5s, 2x timeout)) settles the
 * task from the log state already recorded.
 */
import { createUserMessage } from '@deepseek-ai/dsh-llm'
import type { AgentCancelCause, SessionEvent, UserMessage } from '@deepseek-ai/dsh-session'
import { lookupAgent, type DshContext } from './dsh'
import type { Task } from './task'

export type TaskOutcomeStatus = 'completed' | 'failed' | 'cancelled'

export interface TaskOutcome {
  readonly taskId: string
  readonly status: TaskOutcomeStatus
  readonly text: string | undefined
  readonly error: string | undefined
  readonly durationMs: number
  readonly raw: TaskRawEvents | undefined
}

/** Counts of the tool activity inside this task's turn. */
export interface TaskRawEvents {
  readonly assistantMessages: number
  readonly toolCalls: number
  readonly toolResults: number
  readonly turnEndReason: string | undefined
}

export interface AgentRunnerOptions {
  /**
   * Timeout for tasks that carry no timeoutMs. The plugin entry defaults
   * this to 60s so a hung followup can never hang a run forever.
   */
  readonly defaultTimeoutMs?: number | undefined
}

/** Grace window for whenIdle() convergence after a cancel. */
const CANCEL_GRACE_MS = 5_000

export class AgentRunner {
  readonly #agents: DshContext['agents']
  readonly #defaultTimeoutMs: number | undefined

  constructor(ctx: DshContext, options: AgentRunnerOptions = {}) {
    this.#agents = ctx.agents
    this.#defaultTimeoutMs = options.defaultTimeoutMs
  }

  async run(task: Task, signal?: AbortSignal): Promise<TaskOutcome> {
    const startedAt = Date.now()
    if (signal?.aborted) {
      return {
        taskId: task.id,
        status: 'cancelled',
        text: undefined,
        error: 'cancelled before start',
        durationMs: 0,
        raw: undefined,
      }
    }

    const agent = lookupAgent(this.#agents, task.agentId)
    if (!agent) {
      return {
        taskId: task.id,
        status: 'failed',
        text: undefined,
        error: `agent '${task.agentId}' not found`,
        durationMs: Date.now() - startedAt,
        raw: undefined,
      }
    }

    const timeoutMs = task.timeoutMs ?? this.#defaultTimeoutMs
    const baseline = agent.session.events.length
    const cause: AgentCancelCause = { kind: 'hook', reason: `dsh-multi-agent task '${task.id}'` }

    let signalCancelled = false
    let timer: ReturnType<typeof setTimeout> | undefined
    let onAbort: (() => void) | undefined

    try {
      const converged = await new Promise<boolean>((resolve) => {
        let settled = false
        const settle = (value: boolean): void => {
          if (!settled) {
            settled = true
            resolve(value)
          }
        }
        agent.followup(makeUserMessage(task.prompt))
        agent.whenIdle().then(
          () => settle(true),
          () => settle(true), // whenIdle rejection still means quiescence
        )
        if (timeoutMs !== undefined) {
          timer = setTimeout(() => {
            try {
              agent.cancel(cause)
            } catch {
              // Cancellation is best-effort; outcome is derived from the log state.
            } finally {
              settle(false)
            }
          }, timeoutMs)
        }
        if (signal) {
          onAbort = () => {
            signalCancelled = true
            try {
              agent.cancel(cause)
            } catch {
              // Cancellation is best-effort; preserve the cancellation outcome.
            } finally {
              settle(false)
            }
          }
          signal.addEventListener('abort', onAbort, { once: true })
        }
      })

      if (!converged) {
        // the cancel was issued; give the harness a bounded chance to
        // settle, then read whatever the log already holds
        const grace = Math.max(CANCEL_GRACE_MS, (timeoutMs ?? 0) * 2)
        await Promise.race([
          agent.whenIdle().catch(() => {}),
          new Promise((resolve) => setTimeout(resolve, grace)),
        ])
      }

      const events = agent.session.events.slice(baseline)
      return outcomeFromEvents(task.id, events, {
        cancelledBySignal: signalCancelled || signal?.aborted === true,
        timedOut: !converged && !signalCancelled && signal?.aborted !== true,
        durationMs: Date.now() - startedAt,
      })
    } catch (error) {
      return {
        taskId: task.id,
        status: 'failed',
        text: undefined,
        error: errorMessage(error),
        durationMs: Date.now() - startedAt,
        raw: undefined,
      }
    } finally {
      if (timer !== undefined) clearTimeout(timer)
      if (signal && onAbort !== undefined) signal.removeEventListener('abort', onAbort)
    }
  }
}

/** Build the DSH UserMessage for a prompt (real helper from dsh-llm). */
function makeUserMessage(prompt: string): UserMessage {
  return createUserMessage({
    content: [{ type: 'text', text: prompt }],
    source: { kind: 'user' },
  })
}

interface OutcomeInputs {
  readonly cancelledBySignal: boolean
  readonly timedOut: boolean
  readonly durationMs: number
}

/**
 * Derive the TaskOutcome from this task's session events (the real
 * dsh-session event shapes). Exported for tests.
 */
export function outcomeFromEvents(
  taskId: string,
  events: readonly SessionEvent[],
  inputs: OutcomeInputs,
): TaskOutcome {
  let assistantMessages = 0
  let toolCalls = 0
  let toolResults = 0
  const texts: string[] = []
  let interruptedPrefix: string | undefined
  let turnEndReason: string | undefined
  let turnError: string | undefined

  for (const event of events) {
    const data = event.data as Record<string, unknown> | undefined
    switch (event.type) {
      case 'assistant/message': {
        assistantMessages += 1
        const text = extractText(data?.message)
        if (data?.interrupted === true) {
          interruptedPrefix = text
        } else if (text !== undefined && text !== '') {
          texts.push(text)
        }
        break
      }
      case 'tool/call':
        toolCalls += 1
        break
      case 'tool/result':
        toolResults += 1
        break
      case 'turn/end': {
        const reason = data?.reason as { kind?: string; error?: { message?: string } } | undefined
        turnEndReason = reason?.kind
        if (reason?.kind === 'error' && reason.error?.message !== undefined) {
          turnError = reason.error.message
        }
        break
      }
      default:
        break
    }
  }

  const raw: TaskRawEvents = {
    assistantMessages,
    toolCalls,
    toolResults,
    turnEndReason,
  }
  const joined = texts.length > 0 ? texts.join('\n\n') : undefined

  if (turnEndReason === 'completed') {
    return {
      taskId,
      status: 'completed',
      text: joined,
      error: undefined,
      durationMs: inputs.durationMs,
      raw,
    }
  }
  if (inputs.timedOut) {
    return {
      taskId,
      status: 'failed',
      text: joined ?? interruptedPrefix,
      error: `timeout: turn did not complete (${turnEndReason ?? 'no turn/end'})`,
      durationMs: inputs.durationMs,
      raw,
    }
  }
  if (inputs.cancelledBySignal || turnEndReason === 'aborted') {
    return {
      taskId,
      status: 'cancelled',
      text: joined ?? interruptedPrefix,
      error: inputs.cancelledBySignal ? 'cancelled' : `turn aborted (${turnEndReason ?? 'no turn/end'})`,
      durationMs: inputs.durationMs,
      raw,
    }
  }
  return {
    taskId,
    status: 'failed',
    text: joined ?? interruptedPrefix,
    error: turnError ?? `turn ended: ${turnEndReason ?? 'no turn/end'}`,
    durationMs: inputs.durationMs,
    raw,
  }
}

/** Text blocks of a message, joined; usage-only empties yield undefined. */
function extractText(message: unknown): string | undefined {
  if (typeof message !== 'object' || message === null) return undefined
  const content = (message as { content?: unknown }).content
  if (!Array.isArray(content)) return undefined
  const parts: string[] = []
  for (const block of content) {
    if (
      typeof block === 'object' && block !== null &&
      (block as { type?: unknown }).type === 'text'
    ) {
      const text = (block as { text?: unknown }).text
      if (typeof text === 'string') parts.push(text)
    }
  }
  return parts.length > 0 ? parts.join('') : undefined
}

/** Best-effort message from a thrown value (scheduler error path). */
export function errorMessage(error: unknown): string {
  if (error instanceof Error) return error.message
  return String(error)
}
