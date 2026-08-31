/**
 * Native Recovery — deterministic RecoveryManager.
 *
 * The frozen Supervisor keeps executing exactly one legal run per attempt;
 * Recovery owns the bounded failure decision loop outside the Supervisor.
 * Every repaired or replanned candidate re-enters validation before routing.
 */
import { AgentRouter, PlanValidator, planToSupervisorInput, topologicalOrder } from '../planner'
import type { AgentDescriptor, PlannerPlan, PlanExecutionStrategy, RoutedPlan, RoutedTask } from '../planner/types'
import type { Supervisor, SupervisorRunResult } from '../supervisor'
import type {
  FailureRecord,
  RecoveryDecision,
  RecoveryExecutionContext,
  RecoveryPolicyOptions,
  RecoveryRunOptions,
  RecoveryRunResult,
} from './types'
import { RetryPolicy, delay } from './retry-policy'
import { classifyResult, classifyThrown, extractCompletedTaskIds } from './failure'
import { clearAgentAssignments } from './repair'
import { deterministicReplan } from './replanner'

export interface RecoveryManagerDeps {
  /** The frozen Supervisor V1; one legal run per attempt. */
  readonly supervisor: Supervisor
  /** The default routable agent pool (never mutated). */
  readonly agents: readonly AgentDescriptor[]
  /** Finite retry/replan budget (defaults: 3 attempts / 2 replans). */
  readonly policy?: RecoveryPolicyOptions
}

/**
 * Return the exact routed-task order used by the selected Supervisor strategy.
 * Sequential and relay strategies topologically linearize the routed DAG before
 * assigning synthetic strategy ids; broadcast preserves declaration order.
 */
function strategyTaskOrder(
  routed: RoutedPlan,
  strategy: PlanExecutionStrategy,
): readonly RoutedTask[] {
  return strategy === 'broadcast' ? routed.tasks : topologicalOrder(routed.tasks)
}

/**
 * Map synthetic strategy ids back to Planner ids using the SAME ordered task
 * list that produced those synthetic ids. This prevents recovery from applying
 * a failure to the wrong Planner task when declaration order differs from
 * topological execution order.
 */
function strategyIdToPlanId(
  strategyTaskIds: readonly string[],
  routed: RoutedPlan,
  strategy: PlanExecutionStrategy,
): string[] {
  const ordered = strategyTaskOrder(routed, strategy)
  return strategyTaskIds.map((strategyTaskId) => {
    const match = /^(?:seq|bc|turn|relay)-(\d+)$/.exec(strategyTaskId)
    const index = match !== null ? Number(match[1]) : -1
    return (index >= 0 ? ordered[index]?.id : undefined) ?? strategyTaskId
  })
}

/** Deterministic content id (FNV-1a over the task fields). */
export function planId(plan: PlannerPlan): string {
  let hash = 0x811c9dc5
  const step = (field: string): void => {
    for (let i = 0; i < field.length; i += 1) {
      hash ^= field.charCodeAt(i)
      hash = Math.imul(hash, 0x01000193)
    }
    hash ^= 0x1f
    hash = Math.imul(hash, 0x01000193)
  }
  for (const task of plan.tasks) {
    step(task.id)
    step(task.prompt)
    step(task.agentId ?? '')
    step((task.dependsOn ?? []).join(','))
    step((task.requiredCapabilities ?? []).join(','))
  }
  return `plan-${(hash >>> 0).toString(16)}`
}

export class RecoveryManager {
  readonly #supervisor: Supervisor
  readonly #agents: readonly AgentDescriptor[]
  readonly #policy: RetryPolicy

  constructor(deps: RecoveryManagerDeps) {
    this.#supervisor = deps.supervisor
    this.#agents = deps.agents
    this.#policy = new RetryPolicy(deps.policy)
  }

  /** Recovery budget in effect (for observability / tests). */
  get policy(): RetryPolicy {
    return this.#policy
  }

  /**
   * Execute `plan` under the recovery decision loop. Cancellation via
   * `options.signal` short-circuits everything: no retry, no repair and no
   * replan after cancellation is observed.
   */
  async run(plan: PlannerPlan, options: RecoveryRunOptions): Promise<RecoveryRunResult> {
    const decisions: RecoveryDecision[] = []
    const failures: FailureRecord[] = []
    let currentPlan = plan
    // per-run pool: AGENT_UNAVAILABLE repairs evict the failed agent from it
    let pool = this.#agents
    let attempts = 0
    let repairsUsed = 0
    let replansUsed = 0
    let lastResult: SupervisorRunResult | undefined
    const strategy = options.strategy ?? 'sequential'

    const finish = (
      status: RecoveryRunResult['status'],
      decision: RecoveryDecision,
    ): RecoveryRunResult => {
      decisions.push(decision)
      return {
        runId: options.runId,
        status,
        attempts,
        repairsUsed,
        replansUsed,
        failures,
        decisions,
        lastResult,
      }
    }

    while (true) {
      // cancellation protection: checked before every dispatch and decision
      if (options.signal?.aborted) return finish('cancelled', 'abort')

      if (!this.#policy.canAttempt(attempts + 1)) {
        const exhaustedCode = failures[failures.length - 1]?.code
        return finish(exhaustedCode === 'TIMEOUT' ? 'timeout' : 'failed', 'failed')
      }
      attempts += 1
      const attempt = attempts

      // ---- validate -------------------------------------------------------
      let validatedPlan: PlannerPlan
      try {
        const validator = new PlanValidator({ agents: pool })
        validatedPlan = validator.validateAndRepair(currentPlan).plan
      } catch (error) {
        failures.push(classifyThrown(error, attempt))
        return finish('failed', 'failed')
      }

      // ---- route ----------------------------------------------------------
      let routed: RoutedPlan
      try {
        routed = new AgentRouter({ agents: pool }).route(validatedPlan.tasks)
      } catch (error) {
        failures.push(classifyThrown(error, attempt))
        return finish('failed', 'failed')
      }

      const completedIds =
        lastResult !== undefined ? extractCompletedTaskIds(lastResult) : []
      const lastFailure = failures[failures.length - 1]
      const context: RecoveryExecutionContext = {
        runId: options.runId,
        planId: planId(validatedPlan),
        attempt,
        completedTaskIds: completedIds,
        failedTaskIds: (lastFailure?.taskFailures ?? []).map((ref) => ref.taskId),
        previousFailures: [...failures],
        availableAgents: pool,
      }
      void context

      // ---- execute one legal Supervisor run ------------------------------
      let result: SupervisorRunResult
      try {
        result = await this.#supervisor.run(
          planToSupervisorInput(routed, strategy, {
            runId: options.runId,
            input: options.input,
            ...(options.timeoutMs !== undefined ? { timeoutMs: options.timeoutMs } : {}),
            ...(options.signal !== undefined ? { signal: options.signal } : {}),
            ...(options.metadata !== undefined ? { metadata: options.metadata } : {}),
          }),
        )
      } catch (error) {
        const failure = classifyThrown(error, attempt)
        failures.push(failure)
        if (options.signal?.aborted || failure.code === 'CANCELLED') {
          return finish('cancelled', 'abort')
        }
        // Thrown TIMEOUTs follow the exact same retry policy as returned
        // timeout results; recovery must not depend on error transport shape.
        if (failure.recoverability.retryable && this.#policy.canAttempt(attempt + 1)) {
          decisions.push('retry')
          await delay(this.#policy.delayMs, options.signal)
          continue
        }
        return finish(failure.code === 'TIMEOUT' ? 'timeout' : 'failed', 'failed')
      }

      lastResult = result
      if (result.status === 'completed') {
        return finish('completed', 'completed')
      }

      const failure = classifyResult(result, attempt)
      failures.push(failure)

      // ---- deterministic decision (phase-contract order) -----------------
      if (options.signal?.aborted || failure.code === 'CANCELLED') {
        return finish('cancelled', 'abort')
      }
      if (failure.recoverability.retryable && this.#policy.canAttempt(attempt + 1)) {
        decisions.push('retry')
        await delay(this.#policy.delayMs, options.signal)
        continue
      }
      if (failure.recoverability.repairable) {
        const strategyIds = (failure.taskFailures ?? [])
          .filter((ref) => ref.code === 'AGENT_UNAVAILABLE')
          .map((ref) => ref.taskId)
        const repair = clearAgentAssignments(
          currentPlan,
          strategyIdToPlanId(strategyIds, routed, strategy),
        )
        if (repair.ok) {
          currentPlan = repair.plan
          // re-route guarantee: the dead agent cannot be picked again
          if (failure.agentId !== undefined) {
            pool = pool.filter((agent) => agent.id !== failure.agentId)
          }
          repairsUsed += 1
          decisions.push('repair')
          continue
        }
        // nothing clearable: fall through to replan / failed
      }
      if (failure.recoverability.replanable && this.#policy.canReplan(replansUsed)) {
        const mappedTaskFailures = failure.taskFailures?.map((ref) => ({
          ...ref,
          taskId: strategyIdToPlanId([ref.taskId], routed, strategy)[0]!,
        }))
        const replanFailure: FailureRecord = {
          ...failure,
          ...(mappedTaskFailures !== undefined ? { taskFailures: mappedTaskFailures } : {}),
        }
        const replanned = deterministicReplan({ plan: currentPlan, failure: replanFailure })
        if (replanned.ok) {
          currentPlan = replanned.plan
          replansUsed += 1
          decisions.push('replan')
          continue
        }
      }
      return finish(failure.code === 'TIMEOUT' ? 'timeout' : 'failed', 'failed')
    }
  }
}

/** Convenience factory. */
export function createRecoveryManager(deps: RecoveryManagerDeps): RecoveryManager {
  return new RecoveryManager(deps)
}
