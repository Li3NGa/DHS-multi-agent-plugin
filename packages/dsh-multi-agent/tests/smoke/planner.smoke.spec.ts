/**
 * Native Planner — Phase E3 real-DSH integration smoke.
 *
 * Proves the full E3 pipeline against the REAL DeepSeek Harness:
 *
 *   user input
 *     -> PlannerV1        (scripted PlanSource, real parsing)
 *     -> PlanValidator    (real validation + repair)
 *     -> AgentRouter      (real capability routing)
 *     -> Supervisor V1    (frozen E2 Supervisor)
 *     -> Strategy -> Scheduler -> AgentRunner
 *     -> real DSH Agent / Session / events
 *     -> SupervisorRunResult
 *
 * Only the model endpoint is scripted (ScriptedAdapter via the real
 * ctx.llm.registerAdapter route, as DSH's own tests do). The Planner layer
 * never touches ctx.agents directly — routing happens on AgentDescriptor
 * values, execution goes through the frozen Supervisor.
 *
 * Package tests keep the historical ../src import layout through the
 * tests/src -> ../../src compatibility bridge. The production source remains
 * packages/dsh-multi-agent/src; the bridge is test-only.
 */
import { afterAll, beforeAll, describe, expect, it } from 'vitest'
import { AgentRunner } from '../src/runner'
import type { TaskExecute } from '../src/scheduler'
import { createSupervisor } from '../src/supervisor'
import { createPlanner, planAndRun } from '../src/planner'
import type { AgentDescriptor, SupervisorRunResult } from '../src/index'
import { bootHarness, realAgent, ScriptedAdapter } from './support'

const adapter = new ScriptedAdapter(['echo'], 'echo')
let ctx: Awaited<ReturnType<typeof bootHarness>>

beforeAll(async () => {
  ctx = await bootHarness(adapter)
  realAgent(ctx, 'pl-writer')
  realAgent(ctx, 'pl-critic')
})

afterAll(async () => {
  await (ctx as unknown as { dispose?: () => Promise<void> }).dispose?.()
})

const AGENTS: readonly AgentDescriptor[] = [
  { id: 'pl-writer', capabilities: ['write'] },
  { id: 'pl-critic', capabilities: ['review'] },
]

function pipeline() {
  const runner = new AgentRunner(ctx)
  const execute: TaskExecute = (task, signal) => runner.run(task, signal)
  return {
    planner: createPlanner({
      source: async () =>
        JSON.stringify({
          tasks: [
            { id: 'draft', prompt: 'write the draft', required_capabilities: ['write'] },
            {
              id: 'review',
              prompt: 'review the draft',
              depends_on: ['draft'],
              required_capabilities: ['review'],
            },
          ],
        }),
    }),
    agents: AGENTS,
    supervisor: createSupervisor({ execute }),
  }
}

function sequentialReport(result: SupervisorRunResult) {
  if (result.report.strategy !== 'sequential') throw new Error('expected sequential report')
  return result.report.report
}

describe('Planner V1 — real DSH integration', () => {
  it('plans, validates, routes and runs end-to-end through real DSH', async () => {
    const outcome = await planAndRun('write and review a report', pipeline(), {
      runId: 'planner-e2e',
    })
    expect(outcome.format).toBe('json')
    expect(outcome.validated.issues).toHaveLength(0)
    expect(outcome.routed.assignments.map((assignment) => [assignment.agentId, assignment.reason])).toEqual([
      ['pl-writer', 'capability'],
      ['pl-critic', 'capability'],
    ])
    expect(outcome.supervisorInput.plan.strategy).toBe('sequential')
    expect(outcome.result.status).toBe('completed')
    const report = sequentialReport(outcome.result)
    expect(report.ok).toBe(true)
    expect(report.steps.map((step) => step.text)).toEqual([
      'write the draft',
      'review the draft',
    ])
    expect(outcome.result.errors).toHaveLength(0)
  })

  it('repairs an unknown agent in the plan and still runs through real DSH', async () => {
    const runner = new AgentRunner(ctx)
    const execute: TaskExecute = (task, signal) => runner.run(task, signal)
    const outcome = await planAndRun(
      'repair me',
      {
        planner: createPlanner({
          source: async () =>
            JSON.stringify({
              tasks: [{ id: 'a', prompt: 'do it', agent: 'ghost-agent' }],
            }),
        }),
        agents: AGENTS,
        supervisor: createSupervisor({ execute }),
      },
      { runId: 'planner-repair' },
    )
    expect(outcome.validated.repaired).toBe(true)
    expect(outcome.validated.issues.some((issue) => issue.code === 'unknown-agent')).toBe(true)
    expect(outcome.routed.tasks[0]!.agentId).toBe('pl-writer')
    expect(outcome.result.status).toBe('completed')
  })
})
