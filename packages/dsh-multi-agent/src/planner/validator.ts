import { applyIssueRepairs } from '../recovery/repair'
import { PlanValidationError } from './errors'
import type {
  AgentDescriptor,
  PlanIssue,
  PlanTask,
  PlannerPlan,
  ValidatedPlan,
} from './types'

export interface PlanValidatorDeps {
  readonly agents: readonly AgentDescriptor[]
}

export class PlanValidator {
  readonly #agents: readonly AgentDescriptor[]

  constructor(deps: PlanValidatorDeps) {
    this.#agents = deps.agents
  }

  validate(input: PlannerPlan): ValidatedPlan {
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
    let anyError = false
    const seenIds = new Set<string>()
    const idSet = new Set<string>(tasks.map((task) => task.id))
    const agentIds = new Set<string>(this.#agents.map((agent) => agent.id))

    for (const task of tasks) {
      if (typeof task.id !== 'string' || task.id.length === 0) {
        issues.push({
          severity: 'error',
          code: 'empty-task-id',
          message: 'task id must be a non-empty string',
        })
        anyError = true
        continue
      }
      if (seenIds.has(task.id)) {
        issues.push({
          severity: 'error',
          code: 'duplicate-task-id',
          message: `duplicate task id '${task.id}'`,
          taskId: task.id,
        })
        anyError = true
        continue
      }
      seenIds.add(task.id)

      if (typeof task.prompt !== 'string' || task.prompt.length === 0) {
        issues.push({
          severity: 'error',
          code: 'missing-prompt',
          message: `task '${task.id}' has no prompt`,
          taskId: task.id,
        })
        anyError = true
        continue
      }

      if (task.dependsOn !== undefined) {
        for (const dep of task.dependsOn) {
          if (dep === task.id) {
            issues.push({
              severity: 'error',
              code: 'self-dependency',
              message: `task '${task.id}' depends on itself`,
              taskId: task.id,
            })
            anyError = true
          } else if (!idSet.has(dep)) {
            issues.push({
              severity: 'error',
              code: 'unknown-dependency',
              message: `task '${task.id}' depends on unknown task '${dep}'`,
              taskId: task.id,
            })
            anyError = true
          }
        }
      }

      if (task.agentId !== undefined && !agentIds.has(task.agentId)) {
        issues.push({
          severity: 'warning',
          code: 'unknown-agent',
          message: `task '${task.id}' names unknown agent '${task.agentId}'; reassigning`,
          taskId: task.id,
        })
      }

      if (
        task.requiredCapabilities !== undefined &&
        task.requiredCapabilities.length > 0 &&
        !this.#agents.some((agent) =>
          task.requiredCapabilities!.every((cap) => agent.capabilities.includes(cap)),
        )
      ) {
        issues.push({
          severity: 'warning',
          code: 'unsupported-capability',
          message: `task '${task.id}' requires unsupported capabilities; dropping`,
          taskId: task.id,
        })
      }
    }

    const cycle = findCycle(tasks)
    if (cycle.length > 0) {
      issues.push({
        severity: 'error',
        code: 'cycle',
        message: `dependency cycle: ${cycle.join(' -> ')}`,
      })
      anyError = true
    }

    if (anyError) throw new PlanValidationError('plan failed validation', issues)
    return { plan: { tasks }, issues, repaired: false }
  }

  validateAndRepair(input: PlannerPlan): ValidatedPlan {
    const validated = this.validate(input)
    const repaired = applyIssueRepairs(validated.plan, validated.issues)
    if (repaired === undefined) return validated
    return { plan: repaired.plan, issues: validated.issues, repaired: true }
  }
}

function findCycle(tasks: readonly PlanTask[]): string[] {
  const byId = new Map<string, PlanTask>()
  for (const task of tasks) byId.set(task.id, task)

  const color = new Map<string, number>()
  for (const task of tasks) color.set(task.id, 0)

  for (const root of tasks) {
    if (color.get(root.id) !== 0) continue
    const stack: { id: string; iter: number }[] = [{ id: root.id, iter: 0 }]
    const path: string[] = [root.id]
    color.set(root.id, 1)

    while (stack.length > 0) {
      const frame = stack[stack.length - 1]!
      const deps = byId.get(frame.id)?.dependsOn ?? []
      if (frame.iter < deps.length) {
        const dep = deps[frame.iter]!
        frame.iter += 1
        if (dep === frame.id) continue
        const depColor = color.get(dep) ?? 2
        if (depColor === 1) {
          const start = path.indexOf(dep)
          return [...path.slice(start === -1 ? 0 : start), dep]
        }
        if (depColor === 0 && byId.has(dep)) {
          color.set(dep, 1)
          path.push(dep)
          stack.push({ id: dep, iter: 0 })
        }
      } else {
        color.set(frame.id, 2)
        path.pop()
        stack.pop()
      }
    }
  }
  return []
}

export function createPlanValidator(deps: PlanValidatorDeps): PlanValidator {
  return new PlanValidator(deps)
}
