import { describe, expect, it } from 'vitest'
import { runBroadcast } from '../../src/strategies/broadcast'
import type { TaskExecute } from '../../src/scheduler'

describe('runBroadcast', () => {
  it('asks every agent in parallel and reports in declaration order', async () => {
    const started: string[] = []
    const delays: Record<string, number> = { w1: 20, w2: 1, w3: 10 }
    const execute: TaskExecute = async (task) => {
      started.push(task.id)
      await new Promise((r) => setTimeout(r, delays[task.id] ?? 1))
      return {
        taskId: task.id,
        status: 'completed',
        text: `from-${task.id}`,
        error: undefined,
        durationMs: 1,
        raw: undefined,
      }
    }
    const report = await runBroadcast(execute, {
      prompt: 'question',
      agents: [{ agentId: 'w1' }, { agentId: 'w2' }, { agentId: 'w3' }],
    })
    // all launched before any completed (parallel, not sequential)
    expect(started).toEqual(['bc-0', 'bc-1', 'bc-2'])
    // declaration order regardless of completion order (w2 fastest)
    expect(report.responses.map((r) => r.agentId)).toEqual(['w1', 'w2', 'w3'])
    expect(report.responses.map((r) => r.text)).toEqual(['from-bc-0', 'from-bc-1', 'from-bc-2'])
    expect(report.joined).toBe('from-bc-0\n\nfrom-bc-1\n\nfrom-bc-2')
    expect(report.ok).toBe(true)
  })

  it('isolates per-agent failures', async () => {
    const execute: TaskExecute = async (task) =>
      task.id === 'bc-1'
        ? { taskId: task.id, status: 'failed', text: undefined, error: 'down', durationMs: 1, raw: undefined }
        : { taskId: task.id, status: 'completed', text: task.id, error: undefined, durationMs: 1, raw: undefined }
    const report = await runBroadcast(execute, {
      prompt: 'q',
      agents: [{ agentId: 'a' }, { agentId: 'b' }, { agentId: 'c' }],
    })
    expect(report.ok).toBe(false)
    expect(report.responses[1]!.status).toBe('failed')
    expect(report.joined).toBe('bc-0\n\nbc-2')
  })
})
