/**
 * Native Supervisor V1 — Phase E2 unit tests.
 *
 * These use a fake `execute: TaskExecute` (no real DSH) to verify the
 * Supervisor's orchestration logic quickly: validation, lifecycle, dispatch,
 * cancellation, timeout, aggregation and error propagation. The real-DSH
 * path is covered by smoke/supervisor.smoke.spec.ts.
 */
import { describe, expect, it } from 'vitest'
import {
  Supervisor,
  createSupervisor,
  validateSupervisorInput,
  SupervisorCancellationError,
  SupervisorExecutionError,
  SupervisorTimeoutError,
  SupervisorValidationError,
  isSupervisorError,
} from '../src/supervisor'
import type { TaskExecute } from '../src/scheduler'
import { deferred } from './helpers'
import type { SupervisorRunInput, SupervisorRunResult } from '../src/supervisor/types'

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

const okExecute: TaskExecute = async (task) => ({
  taskId: task.id,
  status: 'completed',
  text: `out-${task.id}`,
  error: undefined,
  durationMs: 1,
  raw: undefined,
})

function makeSupervisor(execute: TaskExecute = okExecute): Supervisor {
  return createSupervisor({ execute })
}

function broadcastPlan(agentIds: string[] = ['alice', 'bob']): SupervisorRunInput {
  return {
    runId: 'run-1',
    input: 'hello',
    plan: {
      strategy: 'broadcast',
      options: { prompt: 'hi', agents: agentIds.map((agentId) => ({ agentId })) },
    },
    metadata: { source: 'unit' },
  }
}

describe('Supervisor V1 — validation', () => {
  it('accepts a valid input plan', () => {
    const plan = validateSupervisorInput(broadcastPlan())
    expect(plan.strategy).toBe('broadcast')
  })

  it('rejects a missing plan', async () => {
    const sup = makeSupervisor()
    await expect(
      sup.run({ runId: 'r', input: 'hi', plan: undefined as never }),
    ).rejects.toMatchObject({ kind: 'validation' })
    expect(sup.state).toBe('failed')
  })

  it('rejects an unknown strategy', async () => {
    const sup = makeSupervisor()
    await expect(
      sup.run({
        runId: 'r',
        input: 'hi',
        plan: { strategy: 'bogus', options: {} } as unknown as SupervisorRunInput['plan'],
      }),
    ).rejects.toBeInstanceOf(SupervisorValidationError)
    expect(sup.state).toBe('failed')
  })

  it('rejects duplicate broadcast agentId', async () => {
    const sup = makeSupervisor()
    await expect(sup.run(broadcastPlan(['alice', 'alice']))).rejects.toBeInstanceOf(
      SupervisorValidationError,
    )
  })

  it('rejects missing broadcast agentId', async () => {
    const sup = makeSupervisor()
    await expect(
      sup.run({
        runId: 'r',
        input: 'hi',
        plan: { strategy: 'broadcast', options: { prompt: 'p', agents: [{} as never] } },
      }),
    ).rejects.toBeInstanceOf(SupervisorValidationError)
  })

  it('rejects an empty runId', async () => {
    const sup = makeSupervisor()
    await expect(
      sup.run({ runId: '', input: 'hi', plan: broadcastPlan().plan }),
    ).rejects.toBeInstanceOf(SupervisorValidationError)
  })
})

describe('Supervisor V1 — happy path per strategy', () => {
  it('broadcast run completes', async () => {
    const result = await makeSupervisor().run(broadcastPlan())
    expect(result.status).toBe('completed')
    expect(result.report.strategy).toBe('broadcast')
    const rep = broadcastReport(result)
    expect(rep.ok).toBe(true)
    expect(rep.responses).toHaveLength(2)
    expect(result.errors).toHaveLength(0)
    expect(result.metadata).toEqual({ source: 'unit' })
    expect(result.durationMs).toBeGreaterThanOrEqual(0)
  })

  it('sequential run completes', async () => {
    const result = await makeSupervisor().run({
      runId: 'r-seq',
      input: 'hi',
      plan: {
        strategy: 'sequential',
        steps: [{ agentId: 'a', prompt: 'p1' }, { agentId: 'b', prompt: 'p2' }],
        options: {},
      },
    })
    expect(result.status).toBe('completed')
    expect(result.report.strategy).toBe('sequential')
    const rep = sequentialReport(result)
    expect(rep.ok).toBe(true)
    expect(rep.steps).toHaveLength(2)
  })

  it('relay run completes', async () => {
    const result = await makeSupervisor().run({
      runId: 'r-relay',
      input: 'hi',
      plan: {
        strategy: 'relay',
        options: { prompt: 'draft me', steps: [{ agentId: 'a' }, { agentId: 'b' }] },
      },
    })
    expect(result.status).toBe('completed')
    expect(result.report.strategy).toBe('relay')
    const rep = relayReport(result)
    expect(rep.ok).toBe(true)
    expect(rep.turns).toHaveLength(2)
  })

  it('empty broadcast plan completes with no responses', async () => {
    const result = await makeSupervisor().run(broadcastPlan([]))
    expect(result.status).toBe('completed')
    expect(broadcastReport(result).responses).toHaveLength(0)
  })
})

describe('Supervisor V1 — cancellation / timeout / failed report', () => {
  it('cancellation via external AbortSignal maps to status cancelled', async () => {
    const gate = deferred<void>()
    const execute: TaskExecute = async (task, signal) => {
      signal.addEventListener('abort', () => gate.resolve(), { once: true })
      await gate.promise
      return {
        taskId: task.id,
        status: 'cancelled',
        text: undefined,
        error: 'cancelled',
        durationMs: 0,
        raw: undefined,
      }
    }
    const sup = makeSupervisor(execute)
    const aborter = new AbortController()
    const run = sup.run({ ...broadcastPlan(), signal: aborter.signal })
    aborter.abort()
    const result = await run
    expect(result.status).toBe('cancelled')
    expect(result.errors).toHaveLength(1)
    expect(result.errors[0]).toBeInstanceOf(SupervisorCancellationError)
    expect(sup.state).toBe('cancelled')
  })

  it('timeout maps to status timeout and reports SupervisorTimeoutError', async () => {
    const gate = deferred<void>()
    const execute: TaskExecute = async (task, signal) => {
      signal.addEventListener('abort', () => gate.resolve(), { once: true })
      await gate.promise
      return {
        taskId: task.id,
        status: 'cancelled',
        text: undefined,
        error: 'cancelled',
        durationMs: 0,
        raw: undefined,
      }
    }
    const sup = makeSupervisor(execute)
    const result = await sup.run({ ...broadcastPlan(), timeoutMs: 25 })
    expect(result.status).toBe('timeout')
    expect(result.errors[0]).toBeInstanceOf(SupervisorTimeoutError)
    expect(sup.state).toBe('timeout')
  })

  it('a report that is not ok maps to status failed', async () => {
    const failExecute: TaskExecute = async (task) => ({
      taskId: task.id,
      status: 'failed',
      text: undefined,
      error: `${task.id}-boom`,
      durationMs: 1,
      raw: undefined,
    })
    const result = await makeSupervisor(failExecute).run(broadcastPlan())
    expect(result.status).toBe('failed')
    expect(broadcastReport(result).ok).toBe(false)
    // per-task errors stay in the report; top-level errors remain empty
    expect(result.errors).toHaveLength(0)
  })
})

describe('Supervisor V1 — execution error propagation', () => {
  it('wraps a strategy failure in SupervisorExecutionError preserving cause', async () => {
    const boom = new Error('boom')
    const sup = createSupervisor({
      execute: okExecute,
      strategies: {
        broadcast: async () => {
          throw boom
        },
      },
    })
    await expect(sup.run(broadcastPlan())).rejects.toBeInstanceOf(SupervisorExecutionError)
    await expect(sup.run(broadcastPlan())).rejects.toMatchObject({
      kind: 'execution',
      cause: boom,
      state: 'failed',
    })
    expect(sup.state).toBe('failed')
  })

  it('never swallows a Runtime error — cause chain is preserved', async () => {
    const inner = new TypeError('runtime-issue')
    const sup = createSupervisor({
      execute: okExecute,
      strategies: {
        sequential: async () => {
          throw inner
        },
      },
    })
    try {
      await sup.run({
        runId: 'r',
        input: 'hi',
        plan: { strategy: 'sequential', steps: [{ agentId: 'a', prompt: 'p' }], options: {} },
      })
      expect.unreachable('should have thrown')
    } catch (error) {
      expect(isSupervisorError(error)).toBe(true)
      expect(error).toBeInstanceOf(SupervisorExecutionError)
      expect((error as SupervisorExecutionError).cause).toBe(inner)
    }
  })
})

describe('Supervisor V1 — lifecycle & aggregation', () => {
  it('tracks lifecycle state through a completed run', async () => {
    const sup = makeSupervisor()
    expect(sup.state).toBe('created')
    await sup.run(broadcastPlan())
    expect(sup.state).toBe('completed')
  })

  it('aggregates a SupervisorRunResult with metadata echo and duration', async () => {
    const result = await makeSupervisor().run(broadcastPlan())
    expect(result.runId).toBe('run-1')
    expect(result.metadata).toEqual({ source: 'unit' })
    expect(typeof result.durationMs).toBe('number')
    expect(result.status).toBe('completed')
    expect(result.report.strategy).toBe('broadcast')
  })
})
