/**
 * RecoveryManager decision loop plus R5 cross-layer regression coverage.
 */
import { describe, expect, it } from 'vitest'
import type { TaskExecute, Task } from '../../src'
import { okOutcome, scriptedExecute } from './helpers'
import { createRecoveryManager } from '../../src/recovery'
import { createSupervisor, SupervisorTimeoutError } from '../../src/supervisor'
import { runSequential } from '../../src/strategies/sequential'

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
    expect(result.failures[0]?.taskFailures?.some((ref) => ref.message === 'kaboom')).toBe(true)
    expect(result.attempts).toBe(1)
  })

  it('R5: recovery maps reordered topological strategy ids to the correct Planner tasks', async () => {
    const execute: TaskExecute = async (task: Task) =>
      task.agentId === 'dead'
        ? {
            taskId: task.id,
            status: 'failed' as const,
            text: undefined,
            error: "agent 'dead' not found",
            durationMs: 1,
            raw: undefined,
          }
        : okOutcome(task.id)
    const manager = createRecoveryManager({
      supervisor: createSupervisor({ execute }),
      agents: [
        { id: 'dead', capabilities: [] },
        { id: 'live-a', capabilities: [] },
        { id: 'live-b', capabilities: [] },
      ],
      policy: { maxAttempts: 3 },
    })

    const result = await manager.run(
      {
        tasks: [
          { id: 'b', agentId: 'dead', prompt: 'B', dependsOn: ['a'] },
          { id: 'a', agentId: 'live-a', prompt: 'A' },
        ],
      },
      { runId: 'r5-reordered', input: 'p' },
    )

    expect(result.status).toBe('completed')
    expect(result.repairsUsed).toBe(1)
    expect(result.decisions).toEqual(['repair', 'completed'])
    expect(result.lastResult?.report.strategy).toBe('sequential')
    if (result.lastResult?.report.strategy === 'sequential') {
      // Topological execution is A -> B. A's explicit live-a assignment must
      // survive recovery; the dead assignment belongs to Planner task B.
      expect(result.lastResult.report.report.steps[0]?.agentId).toBe('live-a')
    }
  })

  it('R5: thrown Supervisor timeout follows the normal retry policy', async () => {
    let calls = 0
    const execute: TaskExecute = async (task) => okOutcome(task.id)
    const supervisor = createSupervisor({
      execute,
      strategies: {
        sequential: async (runExecute, steps, options) => {
          calls += 1
          if (calls === 1) {
            await new Promise<void>((resolve) => setTimeout(resolve, 15))
            throw new Error('forced strategy failure after timeout')
          }
          return runSequential(runExecute, steps, options)
        },
      },
    })
    const manager = createRecoveryManager({
      supervisor,
      agents: [{ id: 'x', capabilities: [] }],
      policy: { maxAttempts: 2 },
    })

    const result = await manager.run(
      { tasks: [{ id: 'a', prompt: 'p' }] },
      { runId: 'r5-timeout', input: 'p', timeoutMs: 1 },
    )

    expect(result.status).toBe('completed')
    expect(result.attempts).toBe(2)
    expect(result.decisions).toEqual(['retry', 'completed'])
    expect(result.failures[0]?.code).toBe('TIMEOUT')
    expect(result.failures[0]?.cause).toBeInstanceOf(SupervisorTimeoutError)
  })

  it('R5: invalid run-level timeout is rejected before dispatch', async () => {
    let calls = 0
    const execute: TaskExecute = async (task) => {
      calls += 1
      return okOutcome(task.id)
    }
    const manager = createRecoveryManager({
      supervisor: createSupervisor({ execute }),
      agents: [{ id: 'x', capabilities: [] }],
    })

    const result = await manager.run(
      { tasks: [{ id: 'a', prompt: 'p' }] },
      { runId: 'r5-invalid-timeout', input: 'p', timeoutMs: 0 },
    )

    expect(result.status).toBe('failed')
    expect(result.failures[0]?.code).toBe('VALIDATION_ERROR')
    expect(calls).toBe(0)
  })
})
