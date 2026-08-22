/**
 * Relay: A -> B -> C refinement of a single draft.
 *
 * Each agent receives the original prompt plus the current draft and
 * returns an improved draft. The context passing model is explicit: an
 * immutable-per-step RelayContext value threaded through the steps by
 * this strategy. The session is never read or mutated for this - the
 * draft lives only inside the relay run.
 */
import { TaskGraph } from '../graph'
import { Scheduler, type SchedulerOptions, type TaskExecute } from '../scheduler'
import type { TaskOutcome } from '../runner'

export interface RelayStep {
  readonly agentId: string
  /** Per-step instruction override for the default wrapper. */
  readonly instruction?: string
  readonly timeoutMs?: number
}

/** What each relay turn sees; a snapshot, never shared mutable state. */
export interface RelayContext {
  readonly step: number
  readonly prompt: string
  readonly draft: string
}

export interface RelayTurn {
  readonly index: number
  readonly taskId: string
  readonly agentId: string
  readonly status: TaskOutcome['status']
  readonly input: string
  readonly output: string | undefined
  readonly error: string | undefined
  readonly durationMs: number
}

export interface RelayReport {
  readonly draft: string
  readonly turns: readonly RelayTurn[]
  readonly ok: boolean
}

export interface RelayOptions extends SchedulerOptions {
  readonly prompt: string
  readonly steps: readonly RelayStep[]
  readonly signal?: AbortSignal
}

const DEFAULT_INSTRUCTION =
  '请改进下面这份草稿，只输出改进后的完整草稿。'

/** Build the message one relay agent sees (the only context carrier). */
export function relayMessage(context: RelayContext, instruction: string): string {
  return `原始任务：${context.prompt}\n\n当前草稿：\n${context.draft}\n\n${instruction}`
}

export async function runRelay(
  execute: TaskExecute,
  options: RelayOptions,
): Promise<RelayReport> {
  const { prompt, steps, signal } = options
  if (steps.length === 0) return { draft: prompt, turns: [], ok: true }

  const graph = new TaskGraph()
  steps.forEach((step, index) => {
    graph.add({
      id: `relay-${index}`,
      agentId: step.agentId,
      prompt,
      dependsOn: index === 0 ? [] : [`relay-${index - 1}`],
      timeoutMs: step.timeoutMs,
      metadata: { relayStep: index },
    })
  })

  // draft propagation, owned by this strategy
  const drafts = new Map<number, string>()
  const turns = new Map<number, RelayTurn>()

  const executeTurn: TaskExecute = async (task, signal) => {
    const index = Number(task.id.slice('relay-'.length))
    const step = steps[index]!
    const context: RelayContext = {
      step: index,
      prompt,
      draft: index === 0 ? prompt : drafts.get(index - 1) ?? prompt,
    }
    const message = relayMessage(context, step.instruction ?? DEFAULT_INSTRUCTION)
    const outcome = await execute(task.withPrompt(message), signal)
    // only successful turns advance the draft; a failed/cancelled turn
    // cancels the rest of the chain via the scheduler's dependency
    // propagation (documented difference to the Python relay, which keeps
    // looping past failed turns)
    if (outcome.status === 'completed' && outcome.text !== undefined) {
      drafts.set(index, outcome.text)
    }
    turns.set(index, {
      index,
      taskId: task.id,
      agentId: step.agentId,
      status: outcome.status,
      input: message,
      output: outcome.text,
      error: outcome.error,
      durationMs: outcome.durationMs,
    })
    return outcome
  }

  const scheduler = new Scheduler(executeTurn, { concurrency: options.concurrency })
  const report = await scheduler.run(graph, signal)

  const turnList: RelayTurn[] = graph.tasks().map((task, index) => {
    const recorded = turns.get(index)
    if (recorded !== undefined) return recorded
    const outcome = report.results.get(task.id)
    return {
      index,
      taskId: task.id,
      agentId: task.agentId,
      status: task.status === 'cancelled' ? 'cancelled' as const : 'failed' as const,
      input: '',
      output: undefined,
      error: outcome?.error ?? task.status,
      durationMs: outcome?.durationMs ?? 0,
    }
  })

  let draft = prompt
  for (let index = 0; index < steps.length; index += 1) {
    const value = drafts.get(index)
    if (value === undefined) break
    draft = value
  }
  return { draft, turns: turnList, ok: report.ok }
}
