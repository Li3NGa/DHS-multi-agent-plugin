/**
 * Native Recovery — Phase E4 Replan V1 (deterministic, no LLM).
 *
 * Single rule, V1: prune-failed-subtree. Given a DEPENDENCY_FAILURE, remove
 * every task that failed plus every task transitively depending on it —
 * those can never run. The surviving sub-plan MUST go through Validator +
 * Router again before execution (the RecoveryManager enforces this); this
 * module only produces candidate plans and never executes anything.
 *
 * Replan explicitly changes semantics (it shrinks the plan); that is what
 * distinguishes it from Repair. It is bounded by RecoveryPolicy.maxReplans.
 */
import type { PlannerPlan } from '../planner/types'
import type { FailureRecord, RecoveryExecutionContext } from './types'

export type ReplanRule = 'prune-failed-subtree'

export type ReplanInput = {
  readonly plan: PlannerPlan
  readonly failure: FailureRecord
  /** Execution context snapshot (runId / attempt / completed / agents...). */
  readonly context?: RecoveryExecutionContext | undefined
}

export type ReplanResult =
  | {
      readonly ok: true
      readonly plan: PlannerPlan
      readonly removedTaskIds: readonly string[]
      readonly rule: ReplanRule
    }
  | {
      readonly ok: false
      readonly code: 'empty-plan' | 'unsupported-failure-code' | 'no-failed-tasks'
      readonly message: string
    }

/** Deterministically prune the failed subtree from the plan. */
export function deterministicReplan(input: ReplanInput): ReplanResult {
  const { plan, failure } = input
  if (failure.code !== 'DEPENDENCY_FAILURE') {
    return {
      ok: false,
      code: 'unsupported-failure-code',
      message: `replan rule 'prune-failed-subtree' only applies to DEPENDENCY_FAILURE (got '${failure.code}')`,
    }
  }
  const remove = new Set<string>((failure.taskFailures ?? []).map((ref) => ref.taskId))
  if (remove.size === 0) {
    return { ok: false, code: 'no-failed-tasks', message: 'failure carries no failed task ids' }
  }
  // transitive closure over dependents
  let grew = true
  while (grew) {
    grew = false
    for (const task of plan.tasks) {
      if (remove.has(task.id)) continue
      if ((task.dependsOn ?? []).some((dep) => remove.has(dep))) {
        remove.add(task.id)
        grew = true
      }
    }
  }
  const kept = plan.tasks.filter((task) => !remove.has(task.id))
  if (kept.length === 0) {
    return {
      ok: false,
      code: 'empty-plan',
      message: 'replan pruned every task; nothing left to execute',
    }
  }
  return {
    ok: true,
    plan: { tasks: kept },
    removedTaskIds: plan.tasks.filter((task) => remove.has(task.id)).map((task) => task.id),
    rule: 'prune-failed-subtree',
  }
}
