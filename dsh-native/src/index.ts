/**
 * DSH native multi-agent orchestration plugin (Phase 2 base runtime).
 *
 * Exposes over ctx.agents:
 * - Task / TaskGraph / Scheduler: the DAG runtime
 * - AgentRunner: task -> ctx.agents execution with timeout & cancellation
 * - strategies: sequential / relay / broadcast
 *
 * The Python runtime under src/deepseek_multi_agent_plugin stays in place
 * as the reference implementation / regression baseline; only behaviour
 * verified there was ported.
 *
 * Cordis wiring: function plugin with `inject: ['agents']`, mounted via
 * cordis.patch.yml pointing at dist/dsh.bundle.js.
 */
import type { DshContext } from './dsh'
import { AgentRunner, type AgentRunnerOptions, type TaskOutcome } from './runner'
import { Scheduler, type SchedulerOptions, type SchedulerReport, type TaskExecute } from './scheduler'
import { TaskGraph, GraphError } from './graph'
import { Task, type TaskSpec, type TaskStatus, type TaskMetadata } from './task'
import { runSequential, type SequentialOptions, type SequentialReport, type SequentialStep } from './strategies/sequential'
import { runRelay, type RelayOptions, type RelayReport } from './strategies/relay'
import { runBroadcast, type BroadcastOptions, type BroadcastReport } from './strategies/broadcast'

export const inject = ['agents']

export interface PluginConfig {
  /** Default max in-flight tasks for schedulers created via ctx.multiAgent. */
  readonly concurrency?: number
  readonly defaultTimeoutMs?: number
}

export interface MultiAgentApi {
  scheduler(options?: SchedulerOptions): Scheduler
  runSequential(steps: readonly SequentialStep[], options?: Omit<SequentialOptions, 'concurrency'>): Promise<SequentialReport>
  runRelay(options: Omit<RelayOptions, 'concurrency'>): Promise<RelayReport>
  runBroadcast(options: Omit<BroadcastOptions, 'concurrency'>): Promise<BroadcastReport>
}

export function apply(ctx: DshContext, config: PluginConfig = {}): void {
  const runner = new AgentRunner(ctx, { defaultTimeoutMs: config.defaultTimeoutMs })
  const execute: TaskExecute = (task, signal) => runner.run(task, signal)

  const api: MultiAgentApi = {
    scheduler: (options) =>
      new Scheduler(execute, { concurrency: config.concurrency, ...options }),
    runSequential: (steps, options) =>
      runSequential(execute, steps, { concurrency: config.concurrency, ...options }),
    runRelay: (options) => runRelay(execute, { concurrency: config.concurrency, ...options }),
    runBroadcast: (options) => runBroadcast(execute, { concurrency: config.concurrency, ...options }),
  }
  ;(ctx as DshContext & { multiAgent?: MultiAgentApi }).multiAgent = api

  if (typeof ctx.on === 'function') {
    ctx.on('dispose', () => {
      delete (ctx as DshContext & { multiAgent?: MultiAgentApi }).multiAgent
    })
  }
}

export {
  AgentRunner,
  Scheduler,
  Task,
  TaskGraph,
  GraphError,
  runSequential,
  runRelay,
  runBroadcast,
}
export type {
  AgentRunnerOptions,
  TaskExecute,
  TaskOutcome,
  TaskSpec,
  TaskStatus,
  TaskMetadata,
  SchedulerOptions,
  SchedulerReport,
  SequentialOptions,
  SequentialReport,
  SequentialStep,
  RelayOptions,
  RelayReport,
  BroadcastOptions,
  BroadcastReport,
  DshContext,
}
