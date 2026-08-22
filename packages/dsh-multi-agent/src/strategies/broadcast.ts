/**
 * Broadcast: every agent answers the same prompt in parallel.
 *
 * Runs on the Scheduler as a flat (dependency-free) graph. Results are
 * deterministic: the report map iterates in agent declaration order even
 * though completion order varies (same guarantee as the Python runtime's
 * registration-order broadcast fix).
 */
import { TaskGraph } from '../graph'
import { Scheduler, type SchedulerOptions, type TaskExecute } from '../scheduler'
import { strategyEnvelope, type StrategyReport } from './contract'

export interface BroadcastAgent {
  readonly agentId: string
  readonly timeoutMs?: number
}

export interface BroadcastOptions extends SchedulerOptions {
  readonly prompt: string
  readonly agents: readonly BroadcastAgent[]
  readonly signal?: AbortSignal
}

export interface BroadcastEntry {
  readonly agentId: string
  readonly taskId: string
  readonly status: 'completed' | 'failed' | 'cancelled'
  readonly text: string | undefined
  readonly error: string | undefined
}

export interface BroadcastReport extends StrategyReport {
  /** One entry per agent, in declaration order. */
  readonly responses: readonly BroadcastEntry[]
  readonly joined: string
}

export async function runBroadcast(
  execute: TaskExecute,
  options: BroadcastOptions,
): Promise<BroadcastReport> {
  const { prompt, agents, signal } = options
  if (agents.length === 0) {
    return { responses: [], joined: '', ...strategyEnvelope('broadcast', false, []) }
  }

  const graph = new TaskGraph()
  agents.forEach((agent, index) => {
    graph.add({
      id: `bc-${index}`,
      agentId: agent.agentId,
      prompt,
      timeoutMs: agent.timeoutMs,
      metadata: { broadcastIndex: index },
    })
  })

  const scheduler = new Scheduler(execute, { concurrency: options.concurrency })
  const report = await scheduler.run(graph, signal)

  const responses: BroadcastEntry[] = agents.map((agent, index) => {
    const outcome = report.results.get(`bc-${index}`)!
    return {
      agentId: agent.agentId,
      taskId: `bc-${index}`,
      status: outcome.status,
      text: outcome.text,
      error: outcome.error,
    }
  })
  const joined = responses
    .filter((entry) => entry.status === 'completed')
    .map((entry) => entry.text)
    .filter((text): text is string => text !== undefined)
    .join('\n\n')
  const tasks = responses.map((entry) => ({
    taskId: entry.taskId,
    agentId: entry.agentId,
    status: entry.status,
    text: entry.text,
    error: entry.error,
  }))
  return {
    responses,
    joined,
    ...strategyEnvelope('broadcast', report.stopped, tasks),
  }
}
