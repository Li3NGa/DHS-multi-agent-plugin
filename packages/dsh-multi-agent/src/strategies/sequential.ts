/**
 * Sequential: A -> B -> C, where each step may use the previous step's
 * result.
 *
 * Two different concepts, deliberately kept apart:
 * - Task dependency: the chain edges in the TaskGraph give the scheduler
 *   its ordering guarantee (B never starts before A completed).
 * - Result/context propagation: passing A's text into B's prompt is done
 *   by THIS strategy (prompt builders receiving the previous result),
 *   not by the scheduler and not by mutating any session.
 */
import { TaskGraph } from '../graph'
import { Scheduler, type SchedulerOptions, type TaskExecute } from '../scheduler'
import { strategyEnvelope, type StrategyReport } from './contract'
import { Task, type TaskMetadata } from '../task'
import type { TaskOutcome } from '../runner'

export interface SequentialStepResult {
  readonly index: number
  readonly taskId: string
  readonly agentId: string
  readonly status: TaskOutcome['status']
  readonly text: string | undefined
  readonly error: string | undefined
  readonly durationMs: number
}

/** Prompt of a step; `previous` is the prior step's result, if any. */
export type SequentialPrompt =
  | string
  | ((previous: SequentialStepResult | undefined, index: number) => string)

export interface SequentialStep {
  readonly agentId: string
  readonly prompt: SequentialPrompt
  readonly timeoutMs?: number
  readonly metadata?: TaskMetadata
}

export interface SequentialReport extends StrategyReport {
  readonly steps: readonly SequentialStepResult[]
  /** Text of the last successful step, if any. */
  readonly final: string | undefined
}

export interface SequentialOptions extends SchedulerOptions {
  readonly signal?: AbortSignal
}

export async function runSequential(
  execute: TaskExecute,
  steps: readonly SequentialStep[],
  options: SequentialOptions = {},
): Promise<SequentialReport> {
  if (steps.length === 0) {
    return { steps: [], final: undefined, ...strategyEnvelope('sequential', false, []) }
  }

  const graph = new TaskGraph()
  steps.forEach((step, index) => {
    graph.add({
      id: `seq-${index}`,
      agentId: step.agentId,
      prompt: typeof step.prompt === 'string' ? step.prompt : '',
      dependsOn: index === 0 ? [] : [`seq-${index - 1}`],
      timeoutMs: step.timeoutMs,
      metadata: { ...step.metadata, stepIndex: index },
    })
  })

  // propagation state, owned by this strategy (never by the scheduler)
  const results = new Map<number, SequentialStepResult>()

  const executeStep: TaskExecute = async (task, signal) => {
    const index = Number(task.id.slice('seq-'.length))
    const step = steps[index]!
    const previous = index > 0 ? results.get(index - 1) : undefined
    const prompt =
      typeof step.prompt === 'function' ? step.prompt(previous, index) : step.prompt
    const outcome = await execute(task.withPrompt(prompt), signal)
    results.set(index, {
      index,
      taskId: task.id,
      agentId: step.agentId,
      status: outcome.status,
      text: outcome.text,
      error: outcome.error,
      durationMs: outcome.durationMs,
    })
    return outcome
  }

  const scheduler = new Scheduler(executeStep, { concurrency: options.concurrency })
  const report = await scheduler.run(graph, options.signal)

  const stepResults = graph.tasks().map((task, index) => {
    const recorded = results.get(index)
    if (recorded !== undefined) return recorded
    // cancelled before execution (dependency chain broken / stop())
    const outcome = report.results.get(task.id)
    return {
      index,
      taskId: task.id,
      agentId: task.agentId,
      status: task.status === 'cancelled' ? ('cancelled' as const) : ('failed' as const),
      text: undefined,
      error: outcome?.error ?? task.status,
      durationMs: outcome?.durationMs ?? 0,
    }
  })
  const lastSuccess = [...stepResults].reverse().find((step) => step.status === 'completed')
  const tasks = stepResults.map((step) => ({
    taskId: step.taskId,
    agentId: step.agentId,
    status: step.status,
    text: step.text,
    error: step.error,
  }))
  return {
    steps: stepResults,
    final: lastSuccess?.text,
    ...strategyEnvelope('sequential', report.stopped, tasks),
  }
}
