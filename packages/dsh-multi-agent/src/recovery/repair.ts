/**
 * Native Recovery — Phase E4 Repair V1.
 *
 * Repair is LOCAL and DETERMINISTIC only. It never re-plans the whole task
 * list and never changes task semantics:
 *   - allowed: drop an invalid explicit agent assignment (Router re-routes);
 *     drop provably-unsatisfiable capability requirements;
 *   - forbidden: touching prompts, ids, dependencies, metadata, or the
 *     task set.
 *
 * This module also OWNS the plan mutations that Phase E3's validator used to
 * perform inline. Since E4 the Validator only JUDGES legality (pure
 * validate()); when a caller wants the historical validate+repair behaviour,
 * validateAndRepair() delegates the mutation here — one implementation, no
 * silent repair inside the validator any more.
 */
import type { PlanIssue, PlannerPlan, PlanTask } from '../planner/types'

/** Issue codes repairable without semantic change. */
const REPAIRABLE_CODES: ReadonlySet<string> = new Set(['unknown-agent', 'unsupported-capability'])

export interface RepairRecord {
  readonly taskId: string
  readonly action: 'drop-agent' | 'drop-capabilities'
  readonly detail: string
}

export interface PlanRepair {
  readonly plan: PlannerPlan
  readonly records: readonly RepairRecord[]
}

export type AssignmentRepairResult =
  | { readonly ok: true; readonly plan: PlannerPlan; readonly records: readonly RepairRecord[] }
  | { readonly ok: false; readonly code: 'nothing-to-repair'; readonly message: string }

function stripField(task: PlanTask, field: 'agentId' | 'requiredCapabilities'): PlanTask {
  const clone: Record<string, unknown> = { ...task }
  delete clone[field]
  return clone as unknown as PlanTask
}

/**
 * Apply validator findings that are safe to repair. Returns undefined when
 * nothing in `issues` is repairable (caller keeps the original plan).
 */
export function applyIssueRepairs(
  plan: PlannerPlan,
  issues: readonly PlanIssue[],
): PlanRepair | undefined {
  const perTask = new Map<string, { dropAgent: boolean; dropCaps: boolean }>()
  let any = false
  for (const issue of issues) {
    if (!REPAIRABLE_CODES.has(issue.code) || issue.taskId === undefined) continue
    any = true
    const entry = perTask.get(issue.taskId) ?? { dropAgent: false, dropCaps: false }
    if (issue.code === 'unknown-agent') entry.dropAgent = true
    else entry.dropCaps = true
    perTask.set(issue.taskId, entry)
  }
  if (!any) return undefined

  const records: RepairRecord[] = []
  const tasks = plan.tasks.map((task) => {
    const fix = perTask.get(task.id)
    if (fix === undefined) return task
    let out = task
    if (fix.dropAgent && out.agentId !== undefined) {
      out = stripField(out, 'agentId')
      records.push({
        taskId: task.id,
        action: 'drop-agent',
        detail: 'unknown explicit agent removed so the Router can reassign',
      })
    }
    if (fix.dropCaps && out.requiredCapabilities !== undefined) {
      out = stripField(out, 'requiredCapabilities')
      records.push({
        taskId: task.id,
        action: 'drop-capabilities',
        detail: 'unsupported capability requirement removed so the task stays routable',
      })
    }
    return out
  })
  return { plan: { tasks }, records }
}

/**
 * Failure-driven repair: clear the explicit agentId of the tasks whose
 * agent turned out to be unavailable, so the Router can assign a live one.
 *
 * Tasks WITHOUT an explicit assignment cannot be repaired this way (the
 * Router already chose the best available agent) — that case is reported as
 * nothing-to-repair instead of silently pretending progress.
 */
export function clearAgentAssignments(
  plan: PlannerPlan,
  taskIds: readonly string[],
): AssignmentRepairResult {
  const targets = new Set(taskIds)
  const records: RepairRecord[] = []
  const tasks = plan.tasks.map((task) => {
    if (!targets.has(task.id)) return task
    if (task.agentId === undefined) return task
    records.push({
      taskId: task.id,
      action: 'drop-agent',
      detail: `unavailable agent '${task.agentId}' cleared for re-routing`,
    })
    return stripField(task, 'agentId')
  })
  if (records.length === 0) {
    return {
      ok: false,
      code: 'nothing-to-repair',
      message: 'no failed task carried an explicit agent assignment to clear',
    }
  }
  return { ok: true, plan: { tasks }, records }
}
