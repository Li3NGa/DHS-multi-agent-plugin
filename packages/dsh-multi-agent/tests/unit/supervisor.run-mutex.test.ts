import { describe, expect, it } from 'vitest'
import type { TaskExecute } from '../../src'
import { createSupervisor } from '../../src/supervisor'

function tick(): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, 0))
}

describe('Supervisor run mutex', () => {
  it('rejects concurrent runs while allowing sequential reuse', async () => {
    let calls = 0
    let releaseFirst: (() => void) | undefined
    const execute: TaskExecute = async (task) => {
      calls += 1
      if (calls === 1) {
        await new Promise<void>((resolve) => {
          releaseFirst = resolve
        })
      }
      return {
        taskId: task.id,
        status: 'completed' as const,
        text: `done:${task.id}`,
        error: undefined,
        durationMs: 1,
        raw: undefined,
      }
    }

    const supervisor = createSupervisor({ execute })
    const input = {
      runId: 'r24-first',
      input: 'hello',
      plan: {
        strategy: 'sequential' as const,
        steps: [{ agentId: 'agent-1', prompt: 'work' }],
      },
    }

    const firstRun = supervisor.run(input)
    await tick()
    expect(supervisor.state).toBe('running')

    await expect(
      supervisor.run({
        ...input,
        runId: 'r24-concurrent',
      }),
    ).rejects.toThrow('Supervisor is already running')
    expect(calls).toBe(1)

    releaseFirst?.()
    const firstResult = await firstRun
    expect(firstResult.status).toBe('completed')
    expect(supervisor.state).toBe('completed')

    const secondResult = await supervisor.run({
      ...input,
      runId: 'r24-second',
    })
    expect(secondResult.status).toBe('completed')
    expect(calls).toBe(2)
    expect(supervisor.state).toBe('completed')
  })
})
