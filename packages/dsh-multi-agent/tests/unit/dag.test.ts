import { describe, expect, it } from 'vitest'
import { runDag } from '../../src/strategies/dag'
import type { TaskOutcome } from '../../src/runner'
import type { TaskSpec } from '../../src/task'

function outcome(taskId: string): TaskOutcome {
  return {
    taskId,
    status: 'completed',
    text: `${taskId}-done`,
    error: undefined,
    durationMs: 1,
    raw: undefined,
  }
}

describe('runDag', () => {
  it('preserves diamond dependencies while allowing independent branches to overlap', async () => {
    const started: string[] = []
    const release = new Map<string, () => void>()
    const specs: readonly TaskSpec[] = [
      { id: 'a', agentId: 'w1', prompt: 'A' },
      { id: 'b', agentId: 'w2', prompt: 'B' },
      { id: 'c', agentId: 'w3', prompt: 'C', dependsOn: ['a', 'b'] },
    ]

    const execute = (task: import('../../src/task').Task): Promise<TaskOutcome> => {
      started.push(task.id)
      return new Promise((resolve) => {
        release.set(task.id, () => resolve(outcome(task.id)))
      })
    }

    const run = runDag(execute, specs, { concurrency: 2 })
    await new Promise((resolve) => setTimeout(resolve, 0))

    expect(started).toEqual(['a', 'b'])
    expect(started).not.toContain('c')

    release.get('a')!()
    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(started).not.toContain('c')

    release.get('b')!()
    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(started).toEqual(['a', 'b', 'c'])

    release.get('c')!()
    const report = await run
    expect(report.ok).toBe(true)
    expect([...report.results.keys()]).toEqual(['a', 'b', 'c'])
    expect(report.results.get('c')?.text).toBe('c-done')
  })

  it('rejects invalid dependency graphs before dispatch', async () => {
    const calls: string[] = []
    await expect(
      runDag(
        async (task) => {
          calls.push(task.id)
          return outcome(task.id)
        },
        [{ id: 'a', agentId: 'w', prompt: 'A', dependsOn: ['missing'] }],
      ),
    ).rejects.toThrow()
    expect(calls).toEqual([])
  })
})
