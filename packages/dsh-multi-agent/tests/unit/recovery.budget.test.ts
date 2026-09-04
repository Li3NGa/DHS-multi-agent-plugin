import { describe, expect, it } from 'vitest'
import type { TaskExecute, Task } from '../../src'
import { okOutcome } from './helpers'
import { createRecoveryManager } from '../../src/recovery'
import { createSupervisor } from '../../src/supervisor'

describe('Recovery budget correctness', () => {
  it('does not repair after the final allowed attempt', async () => {
    let calls = 0
    const execute: TaskExecute = async (task: Task) => {
      calls += 1
      if (task.agentId === 'dead') {
        return {
          taskId: task.id,
          status: 'failed' as const,
          text: undefined,
          error: "agent 'dead' not found",
          durationMs: 1,
          raw: undefined,
        }
      }
      return okOutcome(task.id)
    }

    const manager = createRecoveryManager({
      supervisor: createSupervisor({ execute }),
      agents: [{ id: 'dead', capabilities: [] }, { id: 'live', capabilities: [] }],
      policy: { maxAttempts: 1 },
    })

    const result = await manager.run(
      { tasks: [{ id: 'a', agentId: 'dead', prompt: 'p' }] },
      { runId: 'r22-repair-budget', input: 'p' },
    )

    expect(calls).toBe(1)
    expect(result.status).toBe('failed')
    expect(result.attempts).toBe(1)
    expect(result.repairsUsed).toBe(0)
    expect(result.decisions).toEqual(['failed'])
  })

  it('does not replan after the final allowed attempt', async () => {
    let calls = 0
    const execute: TaskExecute = async (task: Task) => {
      calls += 1
      if (task.id === 'seq-0') {
        return {
          taskId: task.id,
          status: 'failed' as const,
          text: undefined,
          error: 'root failure',
          durationMs: 1,
          raw: undefined,
        }
      }
      return okOutcome(task.id)
    }

    const manager = createRecoveryManager({
      supervisor: createSupervisor({ execute }),
      agents: [{ id: 'x', capabilities: [] }],
      policy: { maxAttempts: 1, maxReplans: 2 },
    })

    const result = await manager.run(
      {
        tasks: [
          { id: 'root', prompt: 'root' },
          { id: 'child', prompt: 'child', dependsOn: ['root'] },
        ],
      },
      { runId: 'r22-replan-budget', input: 'p' },
    )

    expect(calls).toBe(1)
    expect(result.status).toBe('failed')
    expect(result.attempts).toBe(1)
    expect(result.replansUsed).toBe(0)
    expect(result.decisions).toEqual(['failed'])
  })
})
