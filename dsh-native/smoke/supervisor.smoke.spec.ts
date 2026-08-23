/**
 * Native Supervisor V1 — Phase E2 real-DSH integration smoke.
 *
 * Proves the Supervisor reaches the REAL DeepSeek Harness end-to-end:
 *
 *   Supervisor.run(SupervisorRunInput)
 *     -> validateSupervisorInput
 *     -> lifecycle (created..completed)
 *     -> frozen Strategy entry point (runBroadcast/runSequential/runRelay)
 *     -> Scheduler
 *     -> AgentRunner
 *     -> real DSH Agent / Session / events
 *     -> StrategyReport
 *     -> Supervisor aggregation
 *     -> SupervisorRunResult
 *
 * Nothing is mocked except the model endpoint (real ctx.llm.registerAdapter
 * route, as DSH's own tests do). The Supervisor itself never touches
 * ctx.agents / the Session / followup / cancel — it reaches the runtime only
 * through the injected `execute: TaskExecute` (AgentRunner wiring) and the
 * frozen strategies.
 */
import { afterAll, beforeAll, describe, expect, it } from 'vitest'
import { AgentRunner } from '../src/runner'
import type { TaskExecute } from '../src/scheduler'
import { createSupervisor } from '../src/supervisor'
import type { SupervisorRunResult } from '../src/supervisor'
import { bootHarness, realAgent, ScriptedAdapter } from './support'

const adapter = new ScriptedAdapter(['echo'], 'echo')
let ctx: Awaited<ReturnType<typeof bootHarness>>

function broadcastReport(result: SupervisorRunResult) {
  if (result.report.strategy !== 'broadcast') throw new Error('expected broadcast report')
  return result.report.report
}
function sequentialReport(result: SupervisorRunResult) {
  if (result.report.strategy !== 'sequential') throw new Error('expected sequential report')
  return result.report.report
}
function relayReport(result: SupervisorRunResult) {
  if (result.report.strategy !== 'relay') throw new Error('expected relay report')
  return result.report.report
}

beforeAll(async () => {
  ctx = await bootHarness(adapter)
})

afterAll(async () => {
  await (ctx as unknown as { dispose?: () => Promise<void> }).dispose?.()
})

/** Real wiring: Supervisor -> frozen strategy -> Scheduler -> AgentRunner. */
function realSupervisor() {
  const runner = new AgentRunner(ctx)
  const execute: TaskExecute = (task, signal) => runner.run(task, signal)
  return createSupervisor({ execute })
}

describe('Supervisor V1 — real DSH integration', () => {
  it('broadcast run completes through the real DSH runtime', async () => {
    realAgent(ctx, 'sv-b1')
    realAgent(ctx, 'sv-b2')
    const sup = realSupervisor()
    const result = await sup.run({
      runId: 'supervisor-broadcast',
      input: 'echo broadcast',
      plan: {
        strategy: 'broadcast',
        options: { prompt: 'broadcast hello', agents: [{ agentId: 'sv-b1' }, { agentId: 'sv-b2' }] },
      },
    })
    expect(result.status).toBe('completed')
    expect(result.report.strategy).toBe('broadcast')
    expect(broadcastReport(result).ok).toBe(true)
    // echo adapter: each real agent replies with the task prompt
    expect(broadcastReport(result).responses.map((entry) => entry.text)).toEqual([
      'broadcast hello',
      'broadcast hello',
    ])
    expect(result.errors).toHaveLength(0)
    expect(sup.state).toBe('completed')
  })

  it('sequential run threads real results through real turns', async () => {
    realAgent(ctx, 'sv-s1')
    realAgent(ctx, 'sv-s2')
    const result = await realSupervisor().run({
      runId: 'supervisor-sequential',
      input: 'echo seq',
      plan: {
        strategy: 'sequential',
        steps: [{ agentId: 'sv-s1', prompt: 'first' }, { agentId: 'sv-s2', prompt: (prev) => `got: ${prev?.text}` }],
        options: {},
      },
    })
    expect(result.status).toBe('completed')
    expect(result.report.strategy).toBe('sequential')
    expect(sequentialReport(result).steps[0]?.text).toBe('first')
    expect(sequentialReport(result).steps[1]?.text).toBe('got: first')
  })

  it('relay run threads the draft through real turns', async () => {
    realAgent(ctx, 'sv-r1')
    realAgent(ctx, 'sv-r2')
    const result = await realSupervisor().run({
      runId: 'supervisor-relay',
      input: 'echo relay',
      plan: {
        strategy: 'relay',
        options: { prompt: 'start draft', steps: [{ agentId: 'sv-r1' }, { agentId: 'sv-r2' }] },
      },
    })
    expect(result.status).toBe('completed')
    expect(result.report.strategy).toBe('relay')
    expect(relayReport(result).turns[0]?.output).toContain('start draft')
  })
})
