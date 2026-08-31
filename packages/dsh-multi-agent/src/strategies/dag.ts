/**
 * DAG execution: preserve an arbitrary validated dependency graph and let the
 * Runtime Scheduler perform real dependency-aware parallelism.
 */
import { TaskGraph } from '../graph'
import { Scheduler, type SchedulerOptions, type SchedulerReport, type TaskExecute } from '../scheduler'
import type { TaskSpec } from '../task'

export interface DagOptions extends SchedulerOptions {
  readonly signal?: AbortSignal
}

/** Execute an arbitrary TaskSpec DAG with the Runtime Scheduler. */
export async function runDag(
  execute: TaskExecute,
  specs: readonly TaskSpec[],
  options: DagOptions = {},
): Promise<SchedulerReport> {
  const graph = new TaskGraph()
  for (const spec of specs) graph.add(spec)
  const scheduler = new Scheduler(execute, {
    concurrency: options.concurrency,
    ...(options.observer !== undefined ? { observer: options.observer } : {}),
  })
  return scheduler.run(graph, options.signal)
}
