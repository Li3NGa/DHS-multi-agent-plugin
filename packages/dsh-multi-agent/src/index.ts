/** DSH native multi-agent orchestration plugin. */
import type { DshAgentHandle, DshAgentLookup, DshContext, SessionEvent, UserMessage } from './dsh'
import { AgentRunner, type AgentRunnerOptions, type TaskOutcome, type TaskRawEvents } from './runner'
import { Scheduler, type SchedulerOptions, type SchedulerReport, type TaskExecute } from './scheduler'
import { TaskGraph, GraphError } from './graph'
import { Task, type TaskSpec, type TaskStatus, type TaskMetadata } from './task'
import { runSequential, type SequentialOptions, type SequentialReport, type SequentialStep } from './strategies/sequential'
import { runRelay, type RelayOptions, type RelayReport } from './strategies/relay'
import { runBroadcast, type BroadcastOptions, type BroadcastReport } from './strategies/broadcast'
import { runDag, type DagOptions } from './strategies/dag'
import type { StrategyReport, StrategyTask, StrategyError, StrategyMetadata, StrategyKind, StrategyRunStatus } from './strategies/contract'
import { Supervisor, createSupervisor } from './supervisor'
import type { SupervisorRunResult } from './supervisor'
import { createRecoveryManager, type RecoveryManager } from './recovery'
import type { AgentDescriptor, PlannerPlan } from './planner'
import type { RecoveryPolicyOptions, RecoveryRunOptions, RecoveryRunResult } from './recovery'

export const inject = ['agents']
export const DEFAULT_TIMEOUT_MS = 60_000

export interface PluginConfig {
  readonly concurrency?: number | undefined
  readonly defaultTimeoutMs?: number | undefined
  /** Default recovery policy for `runWithRecovery` / `recoveryManager`. */
  readonly recovery?: RecoveryPolicyOptions | undefined
}

export interface RecoveryRunApiOptions extends RecoveryRunOptions {
  /** Routable metadata for the agents used by the plan. */
  readonly agents: readonly AgentDescriptor[]
  /** Per-run override of the plugin's default recovery policy. */
  readonly recovery?: RecoveryPolicyOptions | undefined
}

export interface MultiAgentApi {
  scheduler(options?: SchedulerOptions): Scheduler
  runSequential(steps: readonly SequentialStep[], options?: Omit<SequentialOptions, 'concurrency'>): Promise<SequentialReport>
  runRelay(options: Omit<RelayOptions, 'concurrency'>): Promise<RelayReport>
  runBroadcast(options: Omit<BroadcastOptions, 'concurrency'>): Promise<BroadcastReport>
  /** Execute an arbitrary dependency graph without linearizing it. */
  runDag(tasks: readonly TaskSpec[], options?: Omit<DagOptions, 'concurrency'>): Promise<SchedulerReport>
  /** Create a deterministic RecoveryManager bound to this plugin's executor. */
  recoveryManager(agents: readonly AgentDescriptor[], policy?: RecoveryPolicyOptions): RecoveryManager
  /** Execute one planner plan with bounded retry / repair / replan recovery. */
  runWithRecovery(plan: PlannerPlan, options: RecoveryRunApiOptions): Promise<RecoveryRunResult>
}

export function apply(ctx: DshContext, config: PluginConfig = {}): void {
  const runner = new AgentRunner(ctx, { defaultTimeoutMs: config.defaultTimeoutMs ?? DEFAULT_TIMEOUT_MS })
  const execute: TaskExecute = (task, signal) => runner.run(task, signal)

  const makeRecoveryManager = (
    agents: readonly AgentDescriptor[],
    policy: RecoveryPolicyOptions | undefined,
  ): RecoveryManager => createRecoveryManager({
    supervisor: createSupervisor({ execute }),
    agents,
    ...(policy !== undefined ? { policy } : config.recovery !== undefined ? { policy: config.recovery } : {}),
  })

  const api: MultiAgentApi = {
    scheduler: (options) => new Scheduler(execute, { concurrency: config.concurrency, ...options }),
    runSequential: (steps, options) => runSequential(execute, steps, { concurrency: config.concurrency, ...options }),
    runRelay: (options) => runRelay(execute, { concurrency: config.concurrency, ...options }),
    runBroadcast: (options) => runBroadcast(execute, { concurrency: config.concurrency, ...options }),
    runDag: (tasks, options) => runDag(execute, tasks, { concurrency: config.concurrency, ...options }),
    recoveryManager: (agents, policy) => makeRecoveryManager(agents, policy),
    runWithRecovery: (plan, options) => {
      const { agents, recovery, ...runOptions } = options
      return makeRecoveryManager(agents, recovery).run(plan, runOptions)
    },
  }
  ctx.reflect?.provide('multiAgent', api)
}

export { AgentRunner, Scheduler, Task, TaskGraph, GraphError, runSequential, runRelay, runBroadcast, runDag }
export type { AgentRunnerOptions, TaskExecute, TaskOutcome, TaskRawEvents, TaskSpec, TaskStatus, TaskMetadata, SchedulerOptions, SchedulerReport, SequentialOptions, SequentialReport, SequentialStep, RelayOptions, RelayReport, BroadcastOptions, BroadcastReport, DagOptions, StrategyReport, StrategyTask, StrategyError, StrategyMetadata, StrategyKind, StrategyRunStatus, DshContext, DshAgentHandle, DshAgentLookup, SessionEvent, UserMessage }

export {
  SupervisorError, SupervisorValidationError, SupervisorExecutionError, SupervisorCancellationError, SupervisorTimeoutError, SupervisorAggregationError,
  isSupervisorError, assertTransition, isTerminalState, strategyEntryPoint, assertKnownStrategy,
  Supervisor, createSupervisor, validateSupervisorInput,
} from './supervisor'
export type {
  SupervisorPlan, SupervisorStrategy, SupervisorStrategyReport, SupervisorRunStatus, SupervisorPhase, SupervisorState,
  SupervisorRunInput, SupervisorRunResult, SupervisorSchedulerReport, SupervisorErrorKind, SupervisorErrorFields,
  SupervisorDeps, SupervisorStrategyEntryPoints,
} from './supervisor'

export {
  PlannerError, PlanParseError, PlanValidationError, PlanRoutingError, PlanIntegrationError, isPlannerError,
  PlannerV1, createPlanner, parsePlanText, PlanValidator, createPlanValidator, AgentRouter, createAgentRouter,
  topologicalOrder, routedPlanToSupervisorPlan, planToSupervisorInput, planAndRun, planAndRunDag, createPlanPipeline,
} from './planner'
export type {
  AgentDescriptor, PlanTask, PlannerPlan, PlanFormat, PlanSource, PlannerResult, PlanIssue, PlanIssueSeverity,
  ValidatedPlan, RouteAssignment, RoutedTask, RoutedPlan, PlanExecutionStrategy, PlannedExecutionResult,
  PlannerDeps, PlanValidatorDeps, AgentRouterDeps, PlanPipelineDeps, PlanRunOptions, PlanDagRunOptions, PlannedDagExecutionResult,
} from './planner'

export {
  RECOVERABILITY, classifyThrown, classifyResult, extractTaskFailures, extractCompletedTaskIds,
  RetryPolicy, delay, applyIssueRepairs, clearAgentAssignments, deterministicReplan,
  RecoveryManager, createRecoveryManager, planId,
} from './recovery'
export type {
  FailureCode, Recoverability, TaskFailureRef, FailureRecord, RecoveryExecutionContext, RecoveryDecision,
  RecoveryPolicyOptions, RecoveryRunOptions, RecoveryRunResult, PlanRepair, RepairRecord,
  AssignmentRepairResult, ReplanRule, ReplanInput, ReplanResult, RecoveryManagerDeps,
} from './recovery'
