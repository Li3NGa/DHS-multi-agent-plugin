import { describe, expect, it } from 'vitest'
import { createMetricsCollector, observe } from '../../src/observability'

describe('observability', () => {
  it('collects task and recovery metrics without storing payloads', () => {
    const metrics = createMetricsCollector()

    metrics.observer({
      type: 'task.started',
      at: new Date().toISOString(),
      taskId: 'task-a',
      agentId: 'agent-a',
    })
    metrics.observer({
      type: 'task.finished',
      at: new Date().toISOString(),
      taskId: 'task-a',
      agentId: 'agent-a',
      status: 'failed',
      durationMs: 12,
    })
    metrics.observer({
      type: 'recovery.started',
      at: new Date().toISOString(),
      runId: 'run-1',
      planId: 'plan-1',
    })
    metrics.observer({
      type: 'recovery.attempt',
      at: new Date().toISOString(),
      runId: 'run-1',
      attempt: 1,
    })
    metrics.observer({
      type: 'recovery.failure',
      at: new Date().toISOString(),
      runId: 'run-1',
      attempt: 1,
      code: 'TIMEOUT',
      taskId: 'task-a',
      agentId: 'agent-a',
    })
    metrics.observer({
      type: 'recovery.decision',
      at: new Date().toISOString(),
      runId: 'run-1',
      attempt: 1,
      decision: 'retry',
    })
    metrics.observer({
      type: 'recovery.finished',
      at: new Date().toISOString(),
      runId: 'run-1',
      status: 'completed',
      attempts: 2,
      repairsUsed: 0,
      replansUsed: 0,
      durationMs: 40,
    })

    expect(metrics.snapshot()).toEqual(expect.objectContaining({
      tasksStarted: 1,
      tasksFailed: 1,
      recoveryRuns: 1,
      recoveryAttempts: 1,
      recoveryCompleted: 1,
      failuresByCode: expect.objectContaining({ TIMEOUT: 1 }),
      decisions: expect.objectContaining({ retry: 1 }),
    }))
  })

  it('isolates observer failures from execution', () => {
    const events: string[] = []
    observe(() => {
      events.push('called')
      throw new Error('observer must not break execution')
    }, {
      type: 'recovery.decision',
      at: new Date().toISOString(),
      runId: 'run-1',
      attempt: 1,
      decision: 'completed',
    })
    expect(events).toEqual(['called'])
  })
})
