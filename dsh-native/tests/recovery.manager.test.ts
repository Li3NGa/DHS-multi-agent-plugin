/**
 * Phase E4 — RecoveryManager decision loop (scenarios 13-17).
 */
import { describe, expect, it } from 'vitest'
import type { TaskExecute, Task } from '../src'
import { okOutcome, scriptedExecute } from './helpers'
import { createRecoveryManager } from '../src/recovery'
import { createSupervisor } from '../src/supervisor'

const AGENTS = [{ id: 'x', capabilities: [] }, { id: 'y', capabilities: [] }]

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

describe('Recovery decision loop', () => {
  it('scenario 13: timeout -> retry -> successful execution', async () => {
    let calls = 0
    const execute: TaskExecute = async (task: Task) => {
      calls += 1
      return calls === 1 ? timeoutOutcome(task.id) : okOutcome(task.id)
    }
    const manager = createRecoveryManager({
      supervisor: createSupervisor({ execute }),
      agents: AGENTS,
      policy: { maxAttempts: 3 },
    })
    const result = await manager.run(
      { tasks: [{ id: 'a', prompt: 'pa' }] },
      { runId: 'r13', input: 'p' },
    )
    expect(result.status).toBe('completed')
    expect(result.failures[0]?.code).toBe('TIMEOUT')
    expect(result.attempts).toBe(2)
  })

  it('scenario 14: agent unavailable -> repair/reroute -> success', async () => {
    const execute: TaskExecute = async (task: Task) =>
      task.agentId === 'x'
        ? {
            taskId: task.id,
            status: 'failed' as const,
            text: undefined,
            error: `agent '${task.agentId}' not found`,
            durationMs: 1,
            raw: undefined,
          }
        : okOutcome(task.id)
    const manager = createRecoveryManager({
      supervisor: createSupervisor({ execute }),
      agents: [{ id: 'x', capabilities: [] }, { id: 'y', capabilities: [] }],
      policy: { maxAttempts: 3 },
    })
    const result = await manager.run(
      { tasks: [{ id: 'a', prompt: 'pa', agentId: 'x' }] },
      { runId: 'r14', input: 'p' },
    )
    expect(result.status).toBe('completed')
    expect(result.repairsUsed).toBe(1)
    if (result.lastResult?.report.strategy === 'sequential') {
      expect(result.lastResult.report.report.steps[0]?.agentId).toBe('y')
    }
  })

  it('scenario 15: dependency failure -> deterministic replan -> success', async () => {
    const { execute } = scriptedExecute((task) => (task.id === 'seq-1' ? 'fail' : 'ok'))
    const manager = createRecoveryManager({
      supervisor: createSupervisor({ execute }),
      agents: AGENTS,
      policy: { maxAttempts: 4, maxReplans: 2 },
    })
    const result = await manager.run(
      {
        tasks: [
          { id: 'a', prompt: 'pa' },
          { id: 'b', prompt: 'pb', dependsOn: ['a'] },
          { id: 'c', prompt: 'pc', dependsOn: ['b'] },
        ],
      },
      { runId: 'r15', input: 'p' },
    )
    // attempt1: a ok, b fails, c dep-cascade -> replan prunes b,c -> attempt2 reruns [a]
    expect(result.status).toBe('completed')
    expect(result.replansUsed).toBe(1)
    expect(result.failures[0]?.code).toBe('DEPENDENCY_FAILURE')
    expect(result.decisions).toEqual(['replan', 'completed'])
  })

  it('scenario 16: cancellation -> no retry / repair / replan', async () => {
    const controller = new AbortController()
    let calls = 0
    const execute: TaskExecute = async (task: Task) => {
      calls += 1
      controller.abort()
      void task
      return {
        taskId: task.id,
        status: 'cancelled' as const,
        text: undefined,
        error: 'cancelled',
        durationMs: 1,
        raw: undefined,
      }
    }
    const manager = createRecoveryManager({
      supervisor: createSupervisor({ execute }),
      agents: AGENTS,
      policy: { maxAttempts: 5, maxReplans: 5 },
    })
    const result = await manager.run(
      { tasks: [{ id: 'a', prompt: 'pa' }] },
      { runId: 'r16', input: 'p', signal: controller.signal },
    )
    expect(calls).toBe(1)
    expect(result.status).toBe('cancelled')
    expect(result.decisions).toEqual(['abort'])
    expect(result.attempts).toBe(1)
  })

  it('scenario 17: fatal validation error -> failed with chain preserved', async () => {
    const manager = createRecoveryManager({
      supervisor: createSupervisor({ execute: async (task) => okOutcome(task.id) }),
      agents: AGENTS,
    })
    const result = await manager.run(
      { tasks: [{ id: 'dup', prompt: 'p' }, { id: 'dup', prompt: 'q' }] },
      { runId: 'r17', input: 'p' },
    )
    expect(result.status).toBe('failed')
    expect(result.failures[0]?.code).toBe('VALIDATION_ERROR')
    expect(result.decisions).toEqual(['failed'])
  })

  it('runtime errors surface with cause preserved (no auto recovery)', async () => {
    const execute: TaskExecute = async () => {
      throw new Error('kaboom')
    }
    const manager = createRecoveryManager({
      supervisor: createSupervisor({ execute }),
      agents: AGENTS,
      policy: { maxAttempts: 3 },
    })
    const result = await manager.run(
      { tasks: [{ id: 'a', prompt: 'pa' }] },
      { runId: 'rr', input: 'p' },
    )
    expect(result.status).toBe('failed')
    expect(result.failures[0]?.code).toBe('TASK_ERROR')
    expect(
      result.failures[0]?.taskFailures?.some((ref) => ref.message === 'kaboom'),
    ).toBe(true)
    expect(result.attempts).toBe(1)
  })
})
