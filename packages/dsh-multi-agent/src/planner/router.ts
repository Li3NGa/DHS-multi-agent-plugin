import { PlanRoutingError } from './errors'
import type { AgentDescriptor, PlanTask, RouteAssignment, RoutedPlan } from './types'

export interface AgentRouterDeps {
  readonly agents: readonly AgentDescriptor[]
}

function matchCapabilities(task: PlanTask, agent: AgentDescriptor): boolean {
  const required = task.requiredCapabilities
  return !!required?.length && required.every((cap) => agent.capabilities.includes(cap))
}

export class AgentRouter {
  readonly #agents: readonly AgentDescriptor[]
  #rr = 0

  constructor(deps: AgentRouterDeps) {
    if (deps.agents.length === 0) {
      throw new PlanRoutingError('cannot route with an empty agent pool')
    }
    const ids = new Set<string>()
    for (const agent of deps.agents) {
      if (typeof agent.id !== 'string' || agent.id.length === 0) {
        throw new PlanRoutingError('agent pool contains an agent with an empty id')
      }
      if (ids.has(agent.id)) {
        throw new PlanRoutingError(`agent pool contains duplicate agent id '${agent.id}'`)
      }
      ids.add(agent.id)
    }
    this.#agents = deps.agents
  }

  assign(task: PlanTask): RouteAssignment {
    if (task.agentId !== undefined) {
      const agent = this.#agents.find((candidate) => candidate.id === task.agentId)
      if (agent !== undefined) return { taskId: task.id, agentId: agent.id, reason: 'explicit' }
    }

    if (task.requiredCapabilities?.length) {
      const agent = this.#agents.find((candidate) => matchCapabilities(task, candidate))
      if (agent !== undefined) return { taskId: task.id, agentId: agent.id, reason: 'capability' }
    }

    const agent = this.#agents[this.#rr % this.#agents.length]
    this.#rr += 1
    if (agent === undefined) throw new PlanRoutingError('agent pool is empty', task.id)
    return { taskId: task.id, agentId: agent.id, reason: 'round-robin' }
  }

  route(plan: readonly PlanTask[]): RoutedPlan {
    const assignments = plan.map((task) => this.assign(task))
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

export function createAgentRouter(deps: AgentRouterDeps): AgentRouter {
  return new AgentRouter(deps)
}
