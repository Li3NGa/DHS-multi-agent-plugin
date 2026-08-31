/**
 * Native Planner — Supervisor Integration (Phase E3/E5 boundary).
 *
 * The original integration maps plans onto the FROZEN Supervisor strategies:
 * sequential / broadcast / relay. R3 additionally exposes a direct DAG path:
 *
 *   user input -> Planner -> Validator -> Router -> Scheduler -> AgentRunner
 *
 * This preserves arbitrary dependency edges and therefore permits genuine
 * parallel execution of independent branches. The Supervisor remains frozen
 * to its existing three-strategy contract.
 */
import { PlanIntegrationError } from './errors'
import { AgentRouter } from './router'
import { PlannerV1 } from './planner'
import { PlanValidator } from './validator'
import type { Supervisor, SupervisorRunInput } from '../supervisor'
import type { SupervisorPlan } from '../supervisor/types'
import type { SequentialStep } from '../strategies/sequential'
import { runDag } from '../strategies/dag'
import type { TaskExecute } from '../scheduler'
import type {
  AgentDescriptor,
  PlanDagRunOptions,
  PlanExecutionStrategy,
  PlannedDagExecutionResult,
  PlannedExecutionResult,
  RoutedPlan,
  RoutedTask,
} from './types'

/**
 * Deterministic topological order (Kahn's algorithm, insertion-order
 * tie-breaking). Assumes the plan already passed structural validation
 * (no unknown deps / cycles).
 */
export function topologicalOrder(tasks: readonly RoutedTask[]): RoutedTask[] {
  const pending = new Map(tasks.map((task) => [task.id, new Set(task.dependsOn ?? [])]))
  const order: RoutedTask[] = []
  const done = new Set<string>()

  let progressed = true
  while (order.length < tasks.length && progressed) {
    progressed = false
    for (const task of tasks) {
      if (done.has(task.id)) continue
      const deps = pending.get(task.id)!
      for (const dep of [...deps]) {
        if (done.has(dep)) deps.delete(dep)
      }
      if (deps.size === 0) {
        order.push(task)
        done.add(task.id)
        progressed = true
      }
    }
  }
  if (order.length < tasks.length) {
    throw new PlanIntegrationError('plan is not a DAG (topological sort stalled)')
  }
  return order
}

/** Map a routed plan onto a frozen SupervisorPlan for the chosen strategy. */
export function routedPlanToSupervisorPlan(
  routed: RoutedPlan,
  strategy: PlanExecutionStrategy,
): SupervisorPlan {
  if (routed.tasks.length === 0) {
    throw new PlanIntegrationError('cannot map an empty plan')
  }
  switch (strategy) {
    case 'sequential':
      return sequentialPlan(routed)
    case 'broadcast':
      return broadcastPlan(routed)
    case 'relay':
      return relayPlan(routed)
  }
}

/** Sequential: linearize the DAG topologically; order preserves the edges. */
function sequentialPlan(routed: RoutedPlan): SupervisorPlan {
  const steps: SequentialStep[] = topologicalOrder(routed.tasks).map((task) => ({
    agentId: task.agentId,
    prompt: task.prompt,
    ...(task.timeoutMs !== undefined ? { timeoutMs: task.timeoutMs } : {}),
    ...(task.metadata !== undefined ? { metadata: task.metadata } : {}),
  }))
  return { strategy: 'sequential', steps, options: {} }
}

/** Broadcast: fan-out shape only — independent tasks, one distinct prompt. */
function broadcastPlan(routed: RoutedPlan): SupervisorPlan {
  const prompts = new Set(routed.tasks.map((task) => task.prompt))
  if (prompts.size !== 1) {
    throw new PlanIntegrationError(
      'broadcast mapping requires one shared prompt across all tasks ' +
        `(got ${prompts.size} distinct prompts)`,
    )
  }
  if (routed.tasks.some((task) => (task.dependsOn ?? []).length > 0)) {
    throw new PlanIntegrationError('broadcast mapping requires independent tasks (no dependsOn)')
  }
  const agentIds = new Set<string>()
  for (const task of routed.tasks) {
    if (agentIds.has(task.agentId)) {
      throw new PlanIntegrationError(
        `broadcast mapping produced duplicate agentId '${task.agentId}'`,
      )
    }
    agentIds.add(task.agentId)
  }
  return {
    strategy: 'broadcast',
    options: {
      prompt: routed.tasks[0]!.prompt,
      agents: routed.tasks.map((task) => ({
        agentId: task.agentId,
        ...(task.timeoutMs !== undefined ? { timeoutMs: task.timeoutMs } : {}),
      })),
    },
  }
}

/** Relay: a pure refinement chain — one root, each task at most one dep. */
function relayPlan(routed: RoutedPlan): SupervisorPlan {
  const chain = topologicalOrder(routed.tasks)
  const byId = new Map(chain.map((task) => [task.id, task]))
  for (const task of chain) {
    const deps = task.dependsOn ?? []
    if (deps.length > 1) {
      throw new PlanIntegrationError(
        `relay mapping requires a chain (task '${task.id}' has ${deps.length} dependencies)`,
      )
    }
    for (const dep of deps) {
      if (!byId.has(dep)) {
        throw new PlanIntegrationError(`relay mapping: unknown dependency '${dep}'`)
      }
    }
  }
  const roots = chain.filter((task) => (task.dependsOn ?? []).length === 0)
  if (roots.length !== 1) {
    throw new PlanIntegrationError(
      `relay mapping requires exactly one root task (got ${roots.length})`,
    )
  }
  const dependents = new Map<string, number>()
  for (const task of chain) {
    for (const dep of task.dependsOn ?? []) {
      dependents.set(dep, (dependents.get(dep) ?? 0) + 1)
    }
  }
  if ([...dependents.values()].some((count) => count > 1)) {
    throw new PlanIntegrationError('relay mapping requires a single chain (no fan-out)')
  }
  return {
    strategy: 'relay',
    options: {
      prompt: chain[0]!.prompt,
      steps: chain.map((task, index) => ({
        agentId: task.agentId,
        ...(index > 0 ? { instruction: task.prompt } : {}),
        ...(task.timeoutMs !== undefined ? { timeoutMs: task.timeoutMs } : {}),
      })),
    },
  }
}

/** Build the exact SupervisorRunInput for a routed plan. */
export function planToSupervisorInput(
  routed: RoutedPlan,
  strategy: PlanExecutionStrategy,
  run: {
    readonly runId: string
    readonly input: string
    readonly timeoutMs?: number
    readonly signal?: AbortSignal
    readonly metadata?: Readonly<Record<string, unknown>>
  },
): SupervisorRunInput {
  const plan = routedPlanToSupervisorPlan(routed, strategy)
  return {
    runId: run.runId,
    input: run.input,
    plan,
    ...(run.timeoutMs !== undefined ? { timeoutMs: run.timeoutMs } : {}),
    ...(run.signal !== undefined ? { signal: run.signal } : {}),
    ...(run.metadata !== undefined ? { metadata: run.metadata } : {}),
  }
}

/** Dependencies for the end-to-end plan-and-run pipeline. */
export interface PlanPipelineDeps {
  readonly planner: PlannerV1
  readonly agents: readonly AgentDescriptor[]
  readonly supervisor: Supervisor
}

export interface PlanRunOptions {
  readonly runId: string
  /** Override the strategy mapping (default: 'sequential'). */
  readonly strategy?: PlanExecutionStrategy
  readonly timeoutMs?: number
  readonly signal?: AbortSignal
  readonly metadata?: Readonly<Record<string, unknown>>
}

/**
 * Planner -> Supervisor pipeline for the frozen strategy boundary.
 */
export async function planAndRun(
  input: string,
  deps: PlanPipelineDeps,
  options: PlanRunOptions,
): Promise<PlannedExecutionResult> {
  const { planner, agents, supervisor } = deps
  const strategy = options.strategy ?? 'sequential'

  const planned = await planner.plan(input)
  const validator = new PlanValidator({ agents })
  const validated = validator.validateAndRepair(planned.plan)
  const router = new AgentRouter({ agents })
  const routed = router.route(validated.plan.tasks)

  const supervisorInput = planToSupervisorInput(routed, strategy, {
    runId: options.runId,
    input,
    ...(options.timeoutMs !== undefined ? { timeoutMs: options.timeoutMs } : {}),
    ...(options.signal !== undefined ? { signal: options.signal } : {}),
    ...(options.metadata !== undefined ? { metadata: options.metadata } : {}),
  })
  const result = await supervisor.run(supervisorInput)

  return {
    plan: planned.plan,
    format: planned.format,
    validated,
    routed,
    strategy,
    supervisorInput,
    result,
  }
}

/**
 * Planner -> Validator -> Router -> Scheduler path that preserves the
 * original DAG instead of linearizing it through Supervisor V1.
 */
export async function planAndRunDag(
  input: string,
  execute: TaskExecute,
  deps: Pick<PlanPipelineDeps, 'planner' | 'agents'>,
  options: PlanDagRunOptions,
): Promise<PlannedDagExecutionResult> {
  const startedAt = Date.now()
  const planned = await deps.planner.plan(input)
  const validator = new PlanValidator({ agents: deps.agents })
  const validated = validator.validateAndRepair(planned.plan)
  const routed = new AgentRouter({ agents: deps.agents }).route(validated.plan.tasks)

  const controller = new AbortController()
  const onAbort = (): void => controller.abort()
  if (options.signal?.aborted) controller.abort()
  else options.signal?.addEventListener('abort', onAbort, { once: true })

  const timer =
    options.timeoutMs !== undefined && options.timeoutMs > 0
      ? setTimeout(() => controller.abort(), options.timeoutMs)
      : undefined

  try {
    const report = await runDag(
      execute,
      routed.tasks.map((task) => ({
        id: task.id,
        agentId: task.agentId,
        prompt: task.prompt,
        ...(task.dependsOn !== undefined ? { dependsOn: task.dependsOn } : {}),
        ...(task.timeoutMs !== undefined ? { timeoutMs: task.timeoutMs } : {}),
        ...(task.metadata !== undefined ? { metadata: task.metadata } : {}),
      })),
      {
        concurrency: options.concurrency,
        signal: controller.signal,
      },
    )

    return {
      plan: planned.plan,
      format: planned.format,
      validated,
      routed,
      schedulerReport: report,
      runId: options.runId,
      durationMs: Date.now() - startedAt,
      ...(options.metadata !== undefined ? { metadata: options.metadata } : {}),
    }
  } finally {
    if (timer !== undefined) clearTimeout(timer)
    options.signal?.removeEventListener('abort', onAbort)
  }
}

/** Convenience factory for the whole pipeline around one Supervisor. */
export function createPlanPipeline(
  deps: PlanPipelineDeps,
): (input: string, options: PlanRunOptions) => Promise<PlannedExecutionResult> {
  return (input, options) => planAndRun(input, deps, options)
}
