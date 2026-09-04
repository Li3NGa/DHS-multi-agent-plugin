import { describe, expect, it } from 'vitest'
import type { TaskExecute, Task } from '../../src'
import { okOutcome } from './helpers'
import { createRecoveryManager } from '../../src/recovery'
import { createSupervisor } from '../../src/supervisor'

describe('Recovery repair with multiple unavailable agents', () => {
  it('excludes every unavailable agent observed in the failed broadcast attempt', async () => {
    const calls: string[] = []
    const execute: TaskExecute = async (task: Task) => {
      calls.push(task.agentId)
      if (task.agentId === 'dead-a' || task.agentId === 'dead-b') {
        return {
          taskId: task.id,
          status: 'failed' as const,
          text: undefined,
          error: `agent '${task.agentId}' not found`,
          durationMs: 1,
          raw: undefined,
        }
      }
      return okOutcome(task.id)
    }

    const manager = createRecoveryManager({
      supervisor: createSupervisor({ execute }),
      agents: [
        { id: 'dead-a', capabilities: [] },
        { id: 'dead-b', capabilities: [] },
        { id: 'live', capabilities: [] },
      ],
      policy: { maxAttempts: 2 },
    })

    const result = await manager.run(
      {
        tasks: [
          { id: 'a', agentId: 'dead-a', prompt: 'a' },
          { id: 'b', agentId: 'dead-b', prompt: 'b' },
        ],
      },
      { runId: 'r23-multi-repair', input: 'p', strategy: 'broadcast' },
    )

    expect(result.status).toBe('completed')
    expect(result.attempts).toBe(2)
    expect(result.repairsUsed).toBe(1)
    expect(result.decisions).toEqual(['repair', 'completed'])
    expect(calls).toEqual(['dead-a', 'dead-b', 'live', 'live'])
  })
})
