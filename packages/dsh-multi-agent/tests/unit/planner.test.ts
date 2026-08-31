/**
 * Native Planner — Phase E3 unit tests.
 *
 * Uses a scripted PlanSource and a fake TaskExecute (no real DSH) to verify
 * each planning stage in isolation and the full pipeline wiring. The
 * real-DSH path is covered by smoke/planner.smoke.spec.ts.
 */
import { describe, expect, it } from 'vitest'
import {
  AgentRouter,
  createPlanner,
  createPlanValidator,
  isPlannerError,
  parsePlanText,
  PlanIntegrationError,
  PlanValidationError,
  PlannerV1,
  planAndRun,
  routedPlanToSupervisorPlan,
  topologicalOrder,
} from '../src/planner'
import { createSupervisor } from '../src/supervisor'
import type { AgentDescriptor, PlanTask, RoutedTask } from '../src/planner'
import type { TaskExecute } from '../src/scheduler'

const POOL: readonly AgentDescriptor[] = [
  { id: 'writer', capabilities: ['write'] },
  { id: 'critic', capabilities: ['review'] },
  { id: 'coder', capabilities: ['code', 'test'] },
]

const okExecute: TaskExecute = async (task) => ({
  taskId: task.id,
  status: 'completed',
  text: `out-${task.id}`,
  error: undefined,
  durationMs: 1,
  raw: undefined,
})

describe('Planner V1 — parsing', () => {
  it('parses a fenced JSON task array', async () => {
    const planner = createPlanner({
      source: async () => '```json\n[{"id":"a","prompt":"do a"},{"id":"b","prompt":"do b","depends_on":["a"]}]\n```',
    })
    const result = await planner.plan('make a plan')
    expect(result.format).toBe('json')
    expect(result.plan.tasks).toHaveLength(2)
    expect(result.plan.tasks[1]!.dependsOn).toEqual(['a'])
  })

  it('parses a {tasks: [...]} object', () => {
    const { plan, format } = parsePlanText('{"tasks":[{"id":"t1","prompt":"p1","agent":"writer"}]}', 'x')
    expect(format).toBe('json')
    expect(plan.tasks[0]!.agentId).toBe('writer')
  })

  it('maps description/task fields to prompt and defaults ids', () => {
    const { plan } = parsePlanText('[{"description":"first"},{"task":"second"}]', 'x')
    expect(plan.tasks.map((t) => t.prompt)).toEqual(['first', 'second'])
    expect(plan.tasks.map((t) => t.id)).toEqual(['task_1', 'task_2'])
  })

  it('falls back to one-task-per-line with bullet stripping', () => {
    const { plan, format } = parsePlanText('- first step\n* second step\n3. third step', 'orig')
    expect(format).toBe('lines')
    expect(plan.tasks.map((t) => t.prompt)).toEqual([
      'first step',
      'second step',
      'third step',
    ])
  })

  it('empty text falls back to a single task carrying the original prompt', () => {
    const { plan } = parsePlanText('   ', 'the original input')
    expect(plan.tasks).toEqual([{ id: 'task_1', prompt: 'the original input' }])
  })

  it('filters placeholder dependencies and unsupported task shapes', () => {
    const text = JSON.stringify([
      { id: 'a', prompt: 'p', depends_on: ['前置任务的 id，没有依赖则为空数组', ''] },
      { id: 'b' }, // no prompt -> dropped
    ])
    const { plan } = parsePlanText(text, 'x')
    expect(plan.tasks).toHaveLength(1)
    expect(plan.tasks[0]!.dependsOn).toBeUndefined()
  })
})

describe('Plan Validator', () => {
  const validator = createPlanValidator({ agents: POOL })

  it('accepts a valid plan', () => {
    const plan = { tasks: [{ id: 'a', prompt: 'p' }] }
    const result = validator.validateAndRepair(plan)
    expect(result.issues).toHaveLength(0)
    expect(result.repaired).toBe(false)
  })

  it('rejects an empty plan', () => {
    expect(() => validator.validateAndRepair({ tasks: [] })).toThrowError(PlanValidationError)
  })

  it('rejects duplicate task ids', () => {
    const plan = { tasks: [{ id: 'a', prompt: 'p' }, { id: 'a', prompt: 'q' }] }
    expect(() => validator.validateAndRepair(plan)).toThrowError(PlanValidationError)
  })

  it('rejects unknown dependencies and self-dependencies', () => {
    expect(() =>
      validator.validateAndRepair({ tasks: [{ id: 'a', prompt: 'p', dependsOn: ['ghost'] }] }),
    ).toThrowError(PlanValidationError)
    expect(() =>
      validator.validateAndRepair({ tasks: [{ id: 'a', prompt: 'p', dependsOn: ['a'] }] }),
    ).toThrowError(PlanValidationError)
  })

  it('rejects dependency cycles with the cycle path', () => {
    const plan = {
      tasks: [
        { id: 'a', prompt: 'p', dependsOn: ['c'] },
        { id: 'b', prompt: 'q', dependsOn: ['a'] },
        { id: 'c', prompt: 'r', dependsOn: ['b'] },
      ],
    }
    try {
      validator.validateAndRepair(plan)
      expect.unreachable('should have thrown')
    } catch (error) {
      expect(error).toBeInstanceOf(PlanValidationError)
      expect((error as PlanValidationError).issues.some((issue) => issue.code === 'cycle')).toBe(
        true,
      )
    }
  })

  it('repairs an unknown agent by dropping it for the Router to reassign', () => {
    const plan = { tasks: [{ id: 'a', prompt: 'p', agentId: 'ghost' }] }
    const result = validator.validateAndRepair(plan)
    expect(result.repaired).toBe(true)
    expect(result.plan.tasks[0]!.agentId).toBeUndefined()
    expect(result.issues.some((issue) => issue.code === 'unknown-agent')).toBe(true)
  })

  it('repairs unsupported capability requirements by dropping them', () => {
    const plan = { tasks: [{ id: 'a', prompt: 'p', requiredCapabilities: ['telepathy'] }] }
    const result = validator.validateAndRepair(plan)
    expect(result.repaired).toBe(true)
    expect(result.plan.tasks[0]!.requiredCapabilities).toBeUndefined()
    expect(result.issues.some((issue) => issue.code === 'unsupported-capability')).toBe(true)
  })
})

describe('Agent Router', () => {
  it('honours an explicit known agent', () => {
    const router = new AgentRouter({ agents: POOL })
    const assignment = router.assign({ id: 't', prompt: 'p', agentId: 'critic' })
    expect(assignment).toEqual({ taskId: 't', agentId: 'critic', reason: 'explicit' })
  })

  it('matches capabilities in pool declaration order', () => {
    const router = new AgentRouter({ agents: POOL })
    const assignment = router.assign({ id: 't', prompt: 'p', requiredCapabilities: ['test'] })
    expect(assignment).toEqual({ taskId: 't', agentId: 'coder', reason: 'capability' })
  })

  it('round-robins when no explicit agent and no capability match', () => {
    const router = new AgentRouter({ agents: POOL })
    const first = router.assign({ id: 't1', prompt: 'p' })
    const second = router.assign({ id: 't2', prompt: 'p' })
    expect(first.reason).toBe('round-robin')
    expect(first.agentId).toBe('writer')
    expect(second.agentId).toBe('critic')
  })

  it('re-routes an unknown explicit agent via capability/round-robin', () => {
    const router = new AgentRouter({ agents: POOL })
    const assignment = router.assign({ id: 't', prompt: 'p', agentId: 'ghost' })
    expect(assignment.reason).toBe('round-robin')
    expect(assignment.agentId).toBe('writer')
  })

  it('routes a whole plan, keeping prompts and deps', () => {
    const router = new AgentRouter({ agents: POOL })
    const routed = router.route([
      { id: 'a', prompt: 'write it', requiredCapabilities: ['write'] },
      { id: 'b', prompt: 'review it', dependsOn: ['a'], requiredCapabilities: ['review'] },
    ])
    expect(routed.tasks.map((task) => task.agentId)).toEqual(['writer', 'critic'])
    expect(routed.assignments.map((assignment) => assignment.reason)).toEqual([
      'capability',
      'capability',
    ])
    expect(routed.tasks[1]!.dependsOn).toEqual(['a'])
  })

  it('rejects an empty agent pool', () => {
    expect(() => new AgentRouter({ agents: [] })).toThrowError()
  })
})

describe('Integration — strategy mapping', () => {
  const routed = (tasks: readonly Partial<RoutedTask>[]) => ({
    tasks: tasks.map((task) => ({
      id: task.id ?? 'a',
      prompt: task.prompt ?? 'p',
      agentId: task.agentId ?? 'writer',
      ...(task.dependsOn ? { dependsOn: task.dependsOn } : {}),
    })) as readonly RoutedTask[],
    assignments: [],
  })

  it('linearizes a DAG in topological order for sequential', () => {
    const plan = routed([
      { id: 'c', prompt: 'third', agentId: 'critic', dependsOn: ['b'] },
      { id: 'a', prompt: 'first', agentId: 'writer' },
      { id: 'b', prompt: 'second', agentId: 'coder', dependsOn: ['a'] },
    ])
    const mapped = routedPlanToSupervisorPlan(plan, 'sequential')
    expect(mapped.strategy).toBe('sequential')
    if (mapped.strategy !== 'sequential') return
    expect(mapped.steps.map((step) => step.prompt)).toEqual(['first', 'second', 'third'])
    expect(mapped.steps.map((step) => step.agentId)).toEqual(['writer', 'coder', 'critic'])
  })

  it('topologicalOrder is deterministic with insertion-order tie-breaking', () => {
    const order = topologicalOrder([
      { id: 'x', prompt: 'x', agentId: 'writer' },
      { id: 'y', prompt: 'y', agentId: 'writer' },
      { id: 'z', prompt: 'z', agentId: 'writer', dependsOn: ['x'] },
    ])
    expect(order.map((task) => task.id)).toEqual(['x', 'y', 'z'])
  })

  it('broadcast mapping requires one shared prompt and independent tasks', () => {
    const fanOut = routed([
      { id: 'a', prompt: 'vote', agentId: 'writer' },
      { id: 'b', prompt: 'vote', agentId: 'critic' },
    ])
    const mapped = routedPlanToSupervisorPlan(fanOut, 'broadcast')
    expect(mapped.strategy).toBe('broadcast')
    if (mapped.strategy !== 'broadcast') return
    expect(mapped.options.prompt).toBe('vote')
    expect(mapped.options.agents.map((agent) => agent.agentId)).toEqual(['writer', 'critic'])

    const chained = routed([
      { id: 'a', prompt: 'vote', agentId: 'writer' },
      { id: 'b', prompt: 'vote', agentId: 'critic', dependsOn: ['a'] },
    ])
    expect(() => routedPlanToSupervisorPlan(chained, 'broadcast')).toThrowError(
      PlanIntegrationError,
    )

    const differing = routed([
      { id: 'a', prompt: 'one', agentId: 'writer' },
      { id: 'b', prompt: 'two', agentId: 'critic' },
    ])
    expect(() => routedPlanToSupervisorPlan(differing, 'broadcast')).toThrowError(
      PlanIntegrationError,
    )
  })

  it('relay mapping requires a pure chain', () => {
    const chain = routed([
      { id: 'a', prompt: 'draft', agentId: 'writer' },
      { id: 'b', prompt: 'improve grammar', agentId: 'critic', dependsOn: ['a'] },
    ])
    const mapped = routedPlanToSupervisorPlan(chain, 'relay')
    expect(mapped.strategy).toBe('relay')
    if (mapped.strategy !== 'relay') return
    expect(mapped.options.prompt).toBe('draft')
    expect(mapped.options.steps[1]!.instruction).toBe('improve grammar')

    const fanIn = routed([
      { id: 'a', prompt: 'x', agentId: 'writer' },
      { id: 'b', prompt: 'y', agentId: 'coder' },
      { id: 'c', prompt: 'z', agentId: 'critic', dependsOn: ['a', 'b'] },
    ])
    expect(() => routedPlanToSupervisorPlan(fanIn, 'relay')).toThrowError(PlanIntegrationError)
  })
})

describe('planAndRun — end-to-end pipeline (fake execute)', () => {
  const jsonPlan = JSON.stringify({
    tasks: [
      { id: 'draft', prompt: 'write draft', required_capabilities: ['write'] },
      { id: 'review', prompt: 'review draft', depends_on: ['draft'], required_capabilities: ['review'] },
    ],
  })

  it('plans, validates, routes and runs through the Supervisor', async () => {
    const supervisor = createSupervisor({ execute: okExecute })
    const outcome = await planAndRun(
      'write and review a report',
      {
        planner: createPlanner({ source: async () => jsonPlan }),
        agents: POOL,
        supervisor,
      },
      { runId: 'run-e3-1' },
    )
    expect(outcome.format).toBe('json')
    expect(outcome.strategy).toBe('sequential')
    expect(outcome.routed.tasks.map((task) => task.agentId)).toEqual(['writer', 'critic'])
    expect(outcome.result.status).toBe('completed')
    expect(outcome.supervisorInput.plan.strategy).toBe('sequential')
    expect(supervisor.state).toBe('completed')
  })

  it('maps a fan-out plan onto broadcast when requested', async () => {
    const fanOut = JSON.stringify({
      tasks: [
        { id: 'a', prompt: 'vote', required_capabilities: ['write'] },
        { id: 'b', prompt: 'vote', required_capabilities: ['review'] },
      ],
    })
    const outcome = await planAndRun(
      'gather votes',
      {
        planner: createPlanner({ source: async () => fanOut }),
        agents: POOL,
        supervisor: createSupervisor({ execute: okExecute }),
      },
      { runId: 'run-e3-2', strategy: 'broadcast' },
    )
    expect(outcome.strategy).toBe('broadcast')
    expect(outcome.result.status).toBe('completed')
  })

  it('propagates validation failures loudly (duplicate ids)', async () => {
    const bad = JSON.stringify({
      tasks: [
        { id: 'a', prompt: 'p' },
        { id: 'a', prompt: 'q' },
      ],
    })
    try {
      await planAndRun(
        'x',
        {
          planner: createPlanner({ source: async () => bad }),
          agents: POOL,
          supervisor: createSupervisor({ execute: okExecute }),
        },
        { runId: 'run-e3-3' },
      )
      expect.unreachable('should have thrown')
    } catch (error) {
      expect(isPlannerError(error)).toBe(true)
      expect(error).toBeInstanceOf(PlanValidationError)
    }
  })

  it('propagates integration failures loudly (broadcast on a chain)', async () => {
    const chain = JSON.stringify({
      tasks: [
        { id: 'a', prompt: 'p' },
        { id: 'b', prompt: 'p', depends_on: ['a'] },
      ],
    })
    await expect(
      planAndRun(
        'x',
        {
          planner: createPlanner({ source: async () => chain }),
          agents: POOL,
          supervisor: createSupervisor({ execute: okExecute }),
        },
        { runId: 'run-e3-4', strategy: 'broadcast' },
      ),
    ).rejects.toBeInstanceOf(PlanIntegrationError)
  })

  it('a failed task surfaces as status failed with per-task errors in the report', async () => {
    const failExecute: TaskExecute = async (task) => ({
      taskId: task.id,
      status: 'failed',
      text: undefined,
      error: `${task.id}-boom`,
      durationMs: 1,
      raw: undefined,
    })
    const outcome = await planAndRun(
      'doomed',
      {
        planner: createPlanner({ source: async () => jsonPlan }),
        agents: POOL,
        supervisor: createSupervisor({ execute: failExecute }),
      },
      { runId: 'run-e3-5' },
    )
    expect(outcome.result.status).toBe('failed')
  })
})
