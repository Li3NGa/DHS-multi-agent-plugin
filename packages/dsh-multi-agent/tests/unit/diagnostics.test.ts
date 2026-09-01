import { describe, expect, it } from 'vitest'
import { createRuntimeDiagnostics, RunRegistry } from '../../src/diagnostics'
import { createMetricsCollector } from '../../src/observability'

describe('production diagnostics', () => {
  it('bounds run history and returns newest first', () => {
    const registry = new RunRegistry(2)
    registry.start('run-1', '2026-09-01T00:00:00.000Z')
    registry.start('run-2', '2026-09-01T00:00:01.000Z')
    registry.start('run-3', '2026-09-01T00:00:02.000Z')
    expect(registry.get('run-1')).toBeUndefined()
    expect(registry.list()).toHaveLength(2)
    expect(registry.list()[0]?.runId).toBe('run-3')
  })

  it('ignores lifecycle events after a run reaches a terminal state', () => {
    const registry = new RunRegistry()
    registry.start('run-1', '2026-09-01T00:00:00.000Z')
    registry.attempt('run-1', 1)
    registry.complete('run-1', 'completed', 1, 0, 0, '2026-09-01T00:00:02.000Z')
    registry.attempt('run-1', 9)
    registry.failure('run-1', { at: '2026-09-01T00:00:03.000Z', attempt: 9, code: 'TIMEOUT', taskId: 'task-1', agentId: 'agent-1' })
    registry.decision('run-1', 'retry')
    registry.complete('run-1', 'failed', 9, 1, 1, '2026-09-01T00:00:04.000Z')
    const run = registry.get('run-1')!
    expect(run.status).toBe('completed')
    expect(run.attempts).toBe(1)
    expect(run.failureCount).toBe(0)
    expect(run.decisions).toEqual([])
    expect(run.finishedAt).toBe('2026-09-01T00:00:02.000Z')
  })

  it('ignores orphan lifecycle events', () => {
    const registry = new RunRegistry()
    registry.attempt('missing', 2)
    registry.failure('missing', { at: '2026-09-01T00:00:00.000Z', attempt: 2, code: 'TIMEOUT', taskId: 'task-1', agentId: 'agent-1' })
    registry.decision('missing', 'retry')
    registry.complete('missing', 'failed', 2, 0, 0, '2026-09-01T00:00:01.000Z')
    expect(registry.get('missing')).toBeUndefined()
  })

  it('derives health from bounded runtime signals', () => {
    const metrics = createMetricsCollector()
    const diagnostics = createRuntimeDiagnostics({ metrics, startedAt: 1000, now: () => 5000 })
    expect(diagnostics.health()).toMatchObject({ status: 'healthy', uptimeMs: 4000, activeRuns: 0 })
    metrics.observer({ type: 'task.finished', at: new Date().toISOString(), taskId: 'task-1', agentId: 'agent-1', status: 'failed', durationMs: 10 })
    expect(diagnostics.health().status).toBe('unhealthy')
  })

  it('builds and completes a failure chain without retaining payloads', () => {
    const metrics = createMetricsCollector()
    const diagnostics = createRuntimeDiagnostics({ metrics })
    const observer = diagnostics.observer()
    observer({ type: 'recovery.started', at: '2026-09-01T00:00:00.000Z', runId: 'run-1', planId: 'plan-1' })
    observer({ type: 'recovery.attempt', at: '2026-09-01T00:00:01.000Z', runId: 'run-1', attempt: 1 })
    observer({ type: 'recovery.failure', at: '2026-09-01T00:00:02.000Z', runId: 'run-1', attempt: 1, code: 'TIMEOUT', taskId: 'task-1', agentId: 'agent-1' })
    observer({ type: 'recovery.decision', at: '2026-09-01T00:00:03.000Z', runId: 'run-1', attempt: 1, decision: 'retry' })
    observer({ type: 'recovery.finished', at: '2026-09-01T00:00:04.000Z', runId: 'run-1', status: 'completed', attempts: 2, repairsUsed: 0, replansUsed: 0, durationMs: 4000 })
    const run = diagnostics.inspect('run-1')!
    expect(run.status).toBe('completed')
    expect(run.attempts).toBe(2)
    expect(run.failureCount).toBe(1)
    expect(run.failures[0]).toMatchObject({ code: 'TIMEOUT', taskId: 'task-1' })
    expect(run.decisions).toEqual(['retry'])
    expect(run.finishedAt).toBe('2026-09-01T00:00:04.000Z')
    expect(run).not.toHaveProperty('input')
    expect(run).not.toHaveProperty('metadata')
  })
})
