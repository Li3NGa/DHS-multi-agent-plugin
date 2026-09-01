import { describe, expect, it } from 'vitest'
import { TaskGraph } from '../../src/graph'
import { Scheduler } from '../../src/scheduler'
import type { TaskOutcome } from '../../src/runner'
import { RunRegistry, createRuntimeDiagnostics } from '../../src/diagnostics'
import { createMetricsCollector } from '../../src/observability'

function outcome(taskId: string, status: TaskOutcome['status'] = 'completed'): TaskOutcome {
  return {
    taskId,
    status,
    text: status === 'completed' ? 'ok' : undefined,
    error: status === 'completed' ? undefined : 'expected failure',
    durationMs: 1,
    raw: undefined,
  }
}

function graph(id: string): TaskGraph {
  const graph = new TaskGraph()
  graph.add({ id, agentId: 'agent-1', prompt: id })
  return graph
}

function tick(): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, 0))
}

describe('runtime stability', () => {
  it('reuses one Scheduler across repeated successful runs without state leakage', async () => {
    const scheduler = new Scheduler(async task => outcome(task.id))

    for (let i = 0; i < 250; i += 1) {
      const report = await scheduler.run(graph(`stable-${i}`))
      expect(report.ok).toBe(true)
      expect(report.stopped).toBe(false)
      expect(report.results.size).toBe(1)
    }
  })

  it('recovers Scheduler reuse after failure and cooperative cancellation', async () => {
    let release: (() => void) | undefined
    const blocked = new Promise<void>(resolve => { release = resolve })
    const scheduler = new Scheduler(async task => {
      if (task.id === 'cancel-me') {
        await blocked
        return outcome(task.id)
      }
      if (task.id === 'fail-once') return outcome(task.id, 'failed')
      return outcome(task.id)
    })

    const failed = await scheduler.run(graph('fail-once'))
    expect(failed.ok).toBe(false)
    expect(failed.results.get('fail-once')?.status).toBe('failed')

    const cancelledRun = scheduler.run(graph('cancel-me'))
    await tick()
    scheduler.stop()
    const cancelled = await cancelledRun
    expect(cancelled.stopped).toBe(true)
    expect(cancelled.results.get('cancel-me')?.status).toBe('cancelled')

    release?.()
    await tick()

    const healthy = await scheduler.run(graph('healthy-after-cancel'))
    expect(healthy.ok).toBe(true)
    expect(healthy.results.get('healthy-after-cancel')?.status).toBe('completed')
  })

  it('keeps diagnostics history bounded during repeated run ingestion', () => {
    const metrics = createMetricsCollector()
    const registry = new RunRegistry(32)
    const diagnostics = createRuntimeDiagnostics({ metrics, registry })
    const observer = diagnostics.observer()

    for (let i = 0; i < 500; i += 1) {
      const runId = `diag-${i}`
      observer({ type: 'recovery.started', at: new Date(2026, 8, 1, 0, 0, i % 60).toISOString(), runId, planId: `plan-${i}` })
      observer({ type: 'recovery.attempt', at: new Date().toISOString(), runId, attempt: 1 })
      observer({ type: 'recovery.finished', at: new Date().toISOString(), runId, status: 'completed', attempts: 1, repairsUsed: 0, replansUsed: 0, durationMs: 1 })
    }

    expect(registry.activeCount()).toBe(0)
    expect(registry.list()).toHaveLength(32)
    expect(registry.get('diag-0')).toBeUndefined()
    expect(registry.list()[0]?.runId).toBe('diag-499')
    expect(diagnostics.health().activeRuns).toBe(0)
    expect(metrics.snapshot().recoveryCompleted).toBe(500)
  })
})
