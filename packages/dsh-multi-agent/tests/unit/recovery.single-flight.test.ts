import { describe, expect, it, vi } from 'vitest'
import type { PlannerPlan } from '../../src/planner'
import { createRecoveryManager } from '../../src/recovery'
import { createSupervisor } from '../../src/supervisor'
import { okOutcome } from './helpers'

const plan: PlannerPlan = {
  tasks: [{ id: 'a', prompt: 'p', agentId: 'agent-1' }],
}

function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((innerResolve) => {
    resolve = innerResolve
  })
  return { promise, resolve }
}

describe('RecoveryManager single-flight contract', () => {
  it('rejects overlapping runs and permits sequential reuse', async () => {
    const gate = deferred<void>()
    let calls = 0
    const execute = vi.fn(async (task) => {
      calls += 1
      if (calls === 1) await gate.promise
      return okOutcome(task.id)
    })

    const manager = createRecoveryManager({
      supervisor: createSupervisor({ execute }),
      agents: [{ id: 'agent-1', capabilities: [] }],
    })

    const first = manager.run(plan, { runId: 'r1', input: 'p' })
    await vi.waitFor(() => expect(calls).toBe(1))
    await expect(manager.run(plan, { runId: 'r2', input: 'p' })).rejects.toThrow('RecoveryManager is already running')

    gate.resolve()
    await expect(first).resolves.toMatchObject({ runId: 'r1', status: 'completed', attempts: 1 })
    await expect(manager.run(plan, { runId: 'r3', input: 'p' })).resolves.toMatchObject({ runId: 'r3', status: 'completed', attempts: 1 })
    expect(calls).toBe(2)
  })
})
