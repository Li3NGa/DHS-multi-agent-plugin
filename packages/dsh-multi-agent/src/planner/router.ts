/**
 * Native Agent Router — Phase E3.
 *
 * Assigns a concrete `agentId` to every planned task. Routing precedence
 * (ported from the Python reference `WorkerRouter`, not its internals):
 *   1. explicit — the task declares an `agentId` and it exists in the pool
 *   2. capability — the task requires capabilities; pick the first pool
 *      agent whose declared capabilities cover ALL of them (declaration order)
 *   3. round-robin — fall back to cycling through the pool fairly
 *
 * Deterministic: capability matching iterates the pool in declaration order,
 * so a given (pool, task) pair always resolves identically. Round-robin
 * advances only when actually used, so mixed explicit/capability plans do not
 * skew the counter.
 *
 * Routing never reaches the Runtime directly: it consumes `AgentDescriptor`
 * values supplied by the caller. Unroutable tasks raise PlanRoutingError.
 */
import { PlanRoutingError } from './errors'
import type { AgentDescriptor, PlanTask, RouteAssignment, RoutedPlan } from './types'

export interface AgentRouterDeps {
  /** The pool of routable agents (declaration order is significant). */
  readonly agents: readonly AgentDescriptor[]
}

/**
 * Precedence helpers: 0 = best (explicit), then capability, then round-robin.
 */
function matchCapabilities(task: PlanTask, agent: AgentDescriptor): boolean {
  const required = task.requiredCapabilities
  if (!required || required.length === 0) return false
  return required.every((cap) => agent.capabilities.includes(cap))
}

export class AgentRouter {
  readonly #agents: readonly AgentDescriptor[]
  #rr = 0

  constructor(deps: AgentRouterDeps) {
    if (deps.agents.length === 0) {
      throw new PlanRoutingError('cannot route with an empty agent pool')
    }
    this.#agents = deps.agents
  }

  /** Assign an agent to one task (does not advance round-robin). */
  assign(task: PlanTask): RouteAssignment {
    const explicit = task.agentId
    if (explicit !== undefined) {
      const agent = this.#agents.find((candidate) => candidate.id === explicit)
      if (agent !== undefined) {
        return { taskId: task.id, agentId: agent.id, reason: 'explicit' }
      }
      // explicit agent unknown: fall through to capability / round-robin
    }

    if (task.requiredCapabilities && task.requiredCapabilities.length > 0) {
      const byCap = this.#agents.find((agent) => matchCapabilities(task, agent))
      if (byCap !== undefined) {
        return { taskId: task.id, agentId: byCap.id, reason: 'capability' }
      }
    }

    // round-robin
    const id = this.#rr % this.#agents.length
    const agent = this.#agents[id]
    this.#rr += 1
    if (agent === undefined) {
      throw new PlanRoutingError('agent pool is empty', task.id)
    }
    return { taskId: task.id, agentId: agent.id, reason: 'round-robin' }
  }

  /** Route every task in a plan. Deterministic; never mutates input. */
  route(plan: readonly PlanTask[]): RoutedPlan {
    const assignments: RouteAssignment[] = plan.map((task) => this.assign(task))
    const tasks = plan.map((task, index) => ({
      id: task.id,
      prompt: task.prompt,
      agentId: assignments[index]!.agentId,
      ...(task.dependsOn ? { dependsOn: task.dependsOn } : {}),
      ...(task.timeoutMs !== undefined ? { timeoutMs: task.timeoutMs } : {}),
      ...(task.metadata !== undefined ? { metadata: task.metadata } : {}),
    }))
    return { tasks, assignments }
  }
}

/** Convenience factory. */
export function createAgentRouter(deps: AgentRouterDeps): AgentRouter {
  return new AgentRouter(deps)
}
