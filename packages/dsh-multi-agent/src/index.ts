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
import type { DshAgentHandle, DshAgentLookup, DshContext, SessionEvent, UserMessage } from './dsh'
import { AgentRunner, type AgentRunnerOptions, type TaskOutcome, type TaskRawEvents } from './runner'
import { Scheduler, type SchedulerOptions, type SchedulerReport, type TaskExecute } from './scheduler'
import { TaskGraph, GraphError } from './graph'
import { Task, type TaskSpec, type TaskStatus, type TaskMetadata } from './task'
import { runSequential, type SequentialOptions, type SequentialReport, type SequentialStep } from './strategies/sequential'
import { runRelay, type RelayOptions, type RelayReport } from './strategies/relay'
import { runBroadcast, type BroadcastOptions, type BroadcastReport } from './strategies/broadcast'
import type {
  StrategyReport,
  StrategyTask,
  StrategyError,
  StrategyMetadata,
  StrategyKind,
  StrategyRunStatus,
} from './strategies/contract'

export const inject = ['agents']

/** Tasks without their own timeout get this ceiling (never hang a run). */
export const DEFAULT_TIMEOUT_MS = 60_000

export interface PluginConfig {
  /** Default max in-flight tasks for schedulers created via ctx.multiAgent. */
  readonly concurrency?: number | undefined
  /** Default per-task timeout; defaults to {@link DEFAULT_TIMEOUT_MS}. */
  readonly defaultTimeoutMs?: number | undefined
}

export interface MultiAgentApi {
  scheduler(options?: SchedulerOptions): Scheduler
  runSequential(steps: readonly SequentialStep[], options?: Omit<SequentialOptions, 'concurrency'>): Promise<SequentialReport>
  runRelay(options: Omit<RelayOptions, 'concurrency'>): Promise<RelayReport>
  runBroadcast(options: Omit<BroadcastOptions, 'concurrency'>): Promise<BroadcastReport>
}

export function apply(ctx: DshContext, config: PluginConfig = {}): void {
  const runner = new AgentRunner(ctx, {
    defaultTimeoutMs: config.defaultTimeoutMs ?? DEFAULT_TIMEOUT_MS,
  })
  const execute: TaskExecute = (task, signal) => runner.run(task, signal)

  const api: MultiAgentApi = {
    scheduler: (options) =>
      new Scheduler(execute, { concurrency: config.concurrency, ...options }),
    runSequential: (steps, options) =>
      runSequential(execute, steps, { concurrency: config.concurrency, ...options }),
    runRelay: (options) => runRelay(execute, { concurrency: config.concurrency, ...options }),
    runBroadcast: (options) => runBroadcast(execute, { concurrency: config.concurrency, ...options }),
  }
  // cordis requires services to be provided, not assigned: this unloads
  // automatically with the plugin's fiber
  ctx.reflect?.provide('multiAgent', api)
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
  TaskRawEvents,
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
  StrategyReport,
  StrategyTask,
  StrategyError,
  StrategyMetadata,
  StrategyKind,
  StrategyRunStatus,
  DshContext,
  DshAgentHandle,
  DshAgentLookup,
  SessionEvent,
  UserMessage,
}
