/**
 * Native Plan Validator — Phase E3.
 *
 * Structurally validates a PlannerPlan BEFORE routing, and applies a
 * strictly limited, semantically-safe repair so the plan can proceed:
 *   - drop an unknown explicit `agentId`   -> Router re-assigns
 *   - drop an unsupported required capability -> Router still routable
 *
 * Hard errors (no safe repair) surface as PlanValidationError:
 *   - empty plan
 *   - duplicate / empty task id
 *   - missing prompt
 *   - self-dependency / unknown dependency
 *   - dependency cycle
 *
 * Cycle detection is a depth-first search over the task dependency edges.
 * The validator never calls the Router and never touches the Runtime; it
 * consumes and returns plain `PlannerPlan` values.
 */
import { PlanValidationError } from './errors'
import type {
  AgentDescriptor,
  PlanIssue,
  PlanTask,
  PlannerPlan,
  ValidatedPlan,
} from './types'

export interface PlanValidatorDeps {
  /** The routable agent pool used to judge explicit ids / capabilities. */
  readonly agents: readonly AgentDescriptor[]
}

export class PlanValidator {
  readonly #agents: readonly AgentDescriptor[]

  constructor(deps: PlanValidatorDeps) {
    this.#agents = deps.agents
  }

  /**
   * Validate a plan; repair safe issues and return the (possibly repaired)
   * plan with a full issue trail. Throws PlanValidationError on hard errors.
   */
  validateAndRepair(input: PlannerPlan): ValidatedPlan {
    const tasks = input.tasks
    if (tasks.length === 0) {
      const issue: PlanIssue = {
        severity: 'error',
        code: 'empty-plan',
        message: 'plan contains no tasks',
      }
      throw new PlanValidationError('empty plan', [issue])
    }

    const issues: PlanIssue[] = []
    const repaired: PlanTask[] = []
    let anyRepair = false

    const seenIds = new Set<string>()
    const idSet = new Set<string>(tasks.map((task) => task.id))
    const agentIds = new Set<string>(this.#agents.map((agent) => agent.id))

    for (const task of tasks) {
      let current: PlanTask = task

      // --- id checks ---
      if (typeof current.id !== 'string' || current.id.length === 0) {
        issues.push({
          severity: 'error',
          code: 'empty-task-id',
          message: 'task id must be a non-empty string',
        })
        continue
      }
      if (seenIds.has(current.id)) {
        issues.push({
          severity: 'error',
          code: 'duplicate-task-id',
          message: `duplicate task id '${current.id}'`,
          taskId: current.id,
        })
        continue
      }
      seenIds.add(current.id)

      // --- prompt check ---
      if (typeof current.prompt !== 'string' || current.prompt.length === 0) {
        issues.push({
          severity: 'error',
          code: 'missing-prompt',
          message: `task '${current.id}' has no prompt`,
          taskId: current.id,
        })
        continue
      }

      // --- dependency checks ---
      if (current.dependsOn) {
        for (const dep of current.dependsOn) {
          if (dep === current.id) {
            issues.push({
              severity: 'error',
              code: 'self-dependency',
              message: `task '${current.id}' depends on itself`,
              taskId: current.id,
            })
          } else if (!idSet.has(dep)) {
            issues.push({
              severity: 'error',
              code: 'unknown-dependency',
              message: `task '${current.id}' depends on unknown task '${dep}'`,
              taskId: current.id,
            })
          }
        }
      }

      // --- explicit agent repair (unknown -> let Router assign) ---
      if (current.agentId !== undefined && !agentIds.has(current.agentId)) {
        issues.push({
          severity: 'warning',
          code: 'unknown-agent',
          message: `task '${current.id}' names unknown agent '${current.agentId}'; reassigning`,
          taskId: current.id,
        })
        const { agentId: _dropped, ...rest } = current
        current = rest
        anyRepair = true
      }

      // --- capability repair (unsupported -> drop so it stays routable) ---
      if (current.requiredCapabilities && current.requiredCapabilities.length > 0) {
        const supported = this.#agents.some((agent) =>
          current.requiredCapabilities!.every((cap) => agent.capabilities.includes(cap)),
        )
        if (!supported) {
          issues.push({
            severity: 'warning',
            code: 'unsupported-capability',
            message: `task '${current.id}' requires unsupported capabilities; dropping`,
            taskId: current.id,
          })
          const { requiredCapabilities: _dropped, ...rest } = current
          current = rest
          anyRepair = true
        }
      }

      repaired.push(current)
    }

    // --- cycle detection over the repaired graph ---
    const cycle = findCycle(repaired)
    if (cycle.length > 0) {
      const issue: PlanIssue = {
        severity: 'error',
        code: 'cycle',
        message: `dependency cycle: ${cycle.join(' -> ')}`,
      }
      issues.push(issue)
      throw new PlanValidationError('plan contains a dependency cycle', issues)
    }

    if (issues.some((issue) => issue.severity === 'error')) {
      throw new PlanValidationError('plan failed validation', issues)
    }

    return { plan: { tasks: repaired }, issues, repaired: anyRepair }
  }
}

/** Depth-first cycle detection over dependency edges; returns the cycle path. */
function findCycle(tasks: readonly PlanTask[]): string[] {
  const byId = new Map<string, PlanTask>()
  for (const task of tasks) byId.set(task.id, task)

  const visiting = new Set<string>()
  const visited = new Set<string>()
  const stack: string[] = []

  const visit = (id: string): string[] | undefined => {
    if (visiting.has(id)) {
      const start = stack.indexOf(id)
      return [...stack.slice(start), id]
    }
    if (visited.has(id)) return undefined
    visiting.add(id)
    stack.push(id)
    const task = byId.get(id)
    if (task?.dependsOn) {
      for (const dep of task.dependsOn) {
        if (!byId.has(dep)) continue
        const found = visit(dep)
        if (found) return found
      }
    }
    stack.pop()
    visiting.delete(id)
    visited.add(id)
    return undefined
  }

  for (const task of tasks) {
    const found = visit(task.id)
    if (found) return found
  }
  return []
}

/** Convenience factory. */
export function createPlanValidator(deps: PlanValidatorDeps): PlanValidator {
  return new PlanValidator(deps)
}
