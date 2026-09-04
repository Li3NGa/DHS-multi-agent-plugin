import { describe, expect, it, vi } from 'vitest'
import type { PlannerPlan } from '../../src/planner'
import type { Supervisor, SupervisorRunResult } from '../../src/supervisor'
import { createRecoveryManager } from '../../src/recovery'

function completedResult(runId: string): SupervisorRunResult {
  return {
    runId,
    status: 'completed',
    report: { strategy: 'sequential', report: { ok: true, tasks: [] } } as SupervisorRunResult['report'],
    errors: [],
    metadata: undefined,
    durationMs: 1,
  }
}

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
    const gate = deferred<SupervisorRunResult>()
    const supervisor = {
      run: vi.fn(async (input: { runId: string }) => {
        if (input.runId === 'r1') return gate.promise
        return completedResult(input.runId)
      }),
    } as unknown as Supervisor

    const manager = createRecoveryManager({
      supervisor,
      agents: [{ id: 'agent-1', capabilities: [] }],
    })

    const first = manager.run(plan, { runId: 'r1', input: 'p' })
    await expect(manager.run(plan, { runId: 'r2', input: 'p' })).rejects.toThrow('RecoveryManager is already running')

    gate.resolve(completedResult('r1'))
    await expect(first).resolves.toMatchObject({ runId: 'r1', status: 'completed', attempts: 1 })
    await expect(manager.run(plan, { runId: 'r3', input: 'p' })).resolves.toMatchObject({ runId: 'r3', status: 'completed', attempts: 1 })
    expect(supervisor.run).toHaveBeenCalledTimes(2)
  })
})
