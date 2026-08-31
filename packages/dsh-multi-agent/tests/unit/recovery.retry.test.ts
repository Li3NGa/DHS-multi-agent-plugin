/**
 * Phase E4 — Retry Policy (scenarios 3-5, 13).
 */
import { describe, expect, it } from 'vitest'
import type { TaskExecute, Task } from '../src'
import { okOutcome } from './helpers'
import { createRecoveryManager, RetryPolicy } from '../src/recovery'
import { createSupervisor } from '../src/supervisor'

const PLAN = { tasks: [{ id: 't1', prompt: 'p' }] }

function timeoutOutcome(taskId: string) {
  return {
    taskId,
    status: 'failed' as const,
    text: undefined,
    error: 'timeout: turn did not complete (no turn/end)',
    durationMs: 1,
    raw: undefined,
  }
}

function supervisorWith(execute: TaskExecute) {
  return createSupervisor({ execute })
}

describe('RetryPolicy', () => {
  it('rejects infinite / invalid budgets', () => {
    expect(() => new RetryPolicy({ maxAttempts: Number.POSITIVE_INFINITY })).toThrow()
    expect(() => new RetryPolicy({ maxAttempts: 0 })).toThrow()
    expect(() => new RetryPolicy({ maxReplans: -1 })).toThrow()
  })

  it('guards attempts deterministically', () => {
    const policy = new RetryPolicy({ maxAttempts: 2 })
    expect(policy.canAttempt(1)).toBe(true)
    expect(policy.canAttempt(2)).toBe(true)
    expect(policy.canAttempt(3)).toBe(false)
  })
})

describe('Retry (scenarios 3, 4, 5, 13)', () => {
  it('scenario 3: timeout -> retry -> success', async () => {
    let calls = 0
    const execute: TaskExecute = async (task: Task) => {
      calls += 1
      return calls === 1 ? timeoutOutcome(task.id) : okOutcome(task.id)
    }
    const manager = createRecoveryManager({
      supervisor: supervisorWith(execute),
      agents: [{ id: 'a', capabilities: [] }],
      policy: { maxAttempts: 2 },
    })
    const result = await manager.run(PLAN, { runId: 'r3', input: 'p' })
    expect(result.status).toBe('completed')
    expect(result.attempts).toBe(2)
    expect(result.decisions).toEqual(['retry', 'completed'])
    expect(result.failures[0]?.code).toBe('TIMEOUT')
  })

  it('scenario 4: retry exhausted -> timeout terminal state', async () => {
    let calls = 0
    const execute: TaskExecute = async (task: Task) => {
      calls += 1
      void task
      return timeoutOutcome(`t1-${calls}`)
    }
    const manager = createRecoveryManager({
      supervisor: supervisorWith(execute),
      agents: [{ id: 'a', capabilities: [] }],
      policy: { maxAttempts: 2 },
    })
    const result = await manager.run(PLAN, { runId: 'r4', input: 'p' })
    expect(result.status).toBe('timeout')
    expect(result.attempts).toBe(2)
    expect(result.decisions).toEqual(['retry', 'failed'])
    expect(result.failures.length).toBe(2)
  })

  it('scenario 5: non-retryable failure is not retried', async () => {
    let calls = 0
    const execute: TaskExecute = async (task: Task) => {
      calls += 1
      void task
      return { ...okOutcome(task.id), status: 'failed' as const, text: undefined, error: 'boom' }
    }
    const manager = createRecoveryManager({
      supervisor: supervisorWith(execute),
      agents: [{ id: 'a', capabilities: [] }],
      policy: { maxAttempts: 5 },
    })
    const result = await manager.run(PLAN, { runId: 'r5', input: 'p' })
    expect(calls).toBe(1)
    expect(result.attempts).toBe(1)
    expect(result.decisions).toEqual(['failed'])
    expect(result.failures[0]?.code).toBe('TASK_ERROR')
  })
})
