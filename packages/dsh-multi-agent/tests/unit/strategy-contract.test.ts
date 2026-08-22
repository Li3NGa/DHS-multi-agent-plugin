/**
 * Strategy Contract tests — the ONE shape all three strategies satisfy
 * (docs/runtime-api.md §13). The same invariants run against Broadcast /
 * Sequential / Relay; per-strategy capabilities (parallelism, result
 * propagation, draft threading) are asserted on top of the envelope.
 */
import { describe, expect, it } from 'vitest'
import { runBroadcast } from '../../src/strategies/broadcast'
import { runSequential } from '../../src/strategies/sequential'
import { runRelay } from '../../src/strategies/relay'
import type { StrategyReport, StrategyTask } from '../../src/strategies/contract'
import type { TaskExecute } from '../../src/scheduler'
import type { Task } from '../../src/task'

type AnyReport = StrategyReport

const executeWith =
  (behavior: (task: Task) => { status: 'completed' | 'failed' | 'cancelled'; text?: string; error?: string }): TaskExecute =>
  async (task) => ({
    taskId: task.id,
    status: behavior(task).status,
    text: behavior(task).text ?? undefined,
    error: behavior(task).error ?? undefined,
    durationMs: 1,
    raw: undefined,
  })

const okEcho: TaskExecute = executeWith((task) => ({ status: 'completed', text: `${task.id}-out` }))

async function runEach(
  behavior: TaskExecute,
  signal?: AbortSignal,
): Promise<{ broadcast: AnyReport; sequential: AnyReport; relay: AnyReport }> {
  const broadcast = (await runBroadcast(behavior, {
    prompt: 'p', agents: [{ agentId: 'a' }, { agentId: 'b' }], ...(signal ? { signal } : {}),
  })) as AnyReport
  const sequential = (await runSequential(behavior, [
    { agentId: 'a', prompt: 's0' },
    { agentId: 'b', prompt: () => 's1' },
  ], ...(signal ? [{ signal }] : []))) as AnyReport
  const relay = (await runRelay(behavior, {
    prompt: 'p', steps: [{ agentId: 'a' }, { agentId: 'b' }], ...(signal ? { signal } : {}),
  })) as AnyReport
  return { broadcast, sequential, relay }
}

describe('strategy contract: one envelope for all three', () => {
  it('exposes the identical envelope fields with per-strategy identity', async () => {
    const { broadcast, sequential, relay } = await runEach(okEcho)
    for (const report of [broadcast, sequential, relay]) {
      expect(report.ok).toBe(true)
      expect(report.status).toBe('success')
      expect(report.stopped).toBe(false)
      expect(report.metadata.taskCount).toBe(2)
      expect(report.metadata.completed).toBe(2)
      expect(report.metadata.failed).toBe(0)
      expect(report.metadata.cancelled).toBe(0)
      expect(report.errors).toEqual([])
      expect(report.tasks).toHaveLength(2)
      for (const task of report.tasks as StrategyTask[]) {
        expect(task.status).toBe('completed')
        expect(typeof task.taskId).toBe('string')
        expect(typeof task.agentId).toBe('string')
      }
    }
    expect(broadcast.strategy).toBe('broadcast')
    expect(sequential.strategy).toBe('sequential')
    expect(relay.strategy).toBe('relay')
  })

  it('correlation: uniform tasks map onto the strategy task ids, declaration order', async () => {
    const { broadcast, sequential, relay } = await runEach(okEcho)
    expect(broadcast.tasks.map((t) => t.taskId)).toEqual(['bc-0', 'bc-1'])
    expect(sequential.tasks.map((t) => t.taskId)).toEqual(['seq-0', 'seq-1'])
    expect(relay.tasks.map((t) => t.taskId)).toEqual(['relay-0', 'relay-1'])
    expect(broadcast.tasks.map((t) => t.agentId)).toEqual(['a', 'b'])
  })

  it('error propagation: failed tasks surface in errors[] and metadata, never thrown', async () => {
    const failing = executeWith((task) =>
      task.id.endsWith('1') || task.id === 'bc-1'
        ? { status: 'failed', error: 'agent down' }
        : { status: 'completed', text: 'ok' })
    const { broadcast, sequential, relay } = await runEach(failing)
    for (const report of [broadcast, sequential, relay]) {
      expect(report.ok).toBe(false)
      expect(report.status).toBe('partial') // one completed, one failed
      expect(report.errors).toEqual([{ taskId: report.tasks[1]!.taskId, error: 'agent down' }])
      expect(report.metadata).toEqual({ taskCount: 2, completed: 1, failed: 1, cancelled: 0, timedOut: 0 })
      expect(report.outputs).toEqual(['ok'])
    }
  })

  it('all-failed runs report status failed with empty outputs', async () => {
    const allFail = executeWith(() => ({ status: 'failed', error: 'x' }))
    const { broadcast } = await runEach(allFail)
    expect(broadcast.status).toBe('failed')
    expect(broadcast.outputs).toEqual([])
    expect(broadcast.metadata.completed).toBe(0)
  })

  it('timeout surfaces as failed entries with timeout error text and metadata.timedOut', async () => {
    const timing = executeWith((task) =>
      task.id.endsWith('0')
        ? { status: 'failed', error: 'timeout: turn did not complete (aborted)' }
        : { status: 'completed', text: 'late-agent' })
    const { broadcast, sequential, relay } = await runEach(timing)
    for (const report of [broadcast, sequential, relay]) {
      expect(report.metadata.timedOut).toBe(1)
      expect(report.metadata.failed).toBe(1)
    }
    // broadcast: bc-1 still completes -> partial;
    // sequential/relay: the first step timing out cancels its dependents,
    // so nothing completes -> failed (frozen dependency semantics)
    expect(broadcast.status).toBe('partial')
    expect(sequential.status).toBe('failed')
    expect(relay.status).toBe('failed')
    expect(sequential.tasks[1]!.status).toBe('cancelled')
    expect(relay.metadata.cancelled).toBe(1)
  })

  it('cancellation: stopped run resolves (never throws) with status cancelled and cascade', async () => {
    const hanging: TaskExecute = () => new Promise(() => {}) // never settles
    const controller = new AbortController()
    const runBroadcastPromise = runBroadcast(hanging, {
      prompt: 'p', agents: [{ agentId: 'a' }, { agentId: 'b' }], signal: controller.signal,
    })
    queueMicrotask(() => controller.abort())
    const report = (await runBroadcastPromise) as AnyReport
    expect(report.stopped).toBe(true)
    expect(report.status).toBe('cancelled')
    expect(report.ok).toBe(false)
    expect(report.metadata.cancelled).toBe(2)
    expect(report.tasks.every((t) => t.status === 'cancelled')).toBe(true)
  })

  it('empty input keeps the frozen empty behaviour: success with zero tasks', async () => {
    const emptyBroadcast = (await runBroadcast(okEcho, { prompt: 'p', agents: [] })) as AnyReport
    const emptySequential = (await runSequential(okEcho, [])) as AnyReport
    const emptyRelay = (await runRelay(okEcho, { prompt: 'p', steps: [] })) as AnyReport
    for (const report of [emptyBroadcast, emptySequential, emptyRelay]) {
      expect(report.ok).toBe(true)
      expect(report.status).toBe('success')
      expect(report.metadata.taskCount).toBe(0)
      expect(report.tasks).toEqual([])
    }
  })
})

describe('per-strategy capabilities stay internal', () => {
  it('broadcast runs agents in parallel', async () => {
    let inflight = 0
    let peak = 0
    const parallel: TaskExecute = async (task) => {
      inflight += 1
      peak = Math.max(peak, inflight)
      await new Promise((r) => setTimeout(r, 5))
      inflight -= 1
      return { taskId: task.id, status: 'completed', text: 'x', error: undefined, durationMs: 1, raw: undefined }
    }
    const report = (await runBroadcast(parallel, {
      prompt: 'p',
      agents: [{ agentId: 'a' }, { agentId: 'b' }, { agentId: 'c' }],
    })) as AnyReport
    expect(peak).toBe(3) // all three in flight together
    expect(report.metadata.completed).toBe(3)
  })

  it('sequential: previous result reaches the next prompt', async () => {
    const prompts: string[] = []
    const execute: TaskExecute = async (task) => {
      prompts.push(task.prompt)
      return { taskId: task.id, status: 'completed', text: `out-${task.id}`, error: undefined, durationMs: 1, raw: undefined }
    }
    const report = (await runSequential(execute, [
      { agentId: 'a', prompt: 'first' },
      { agentId: 'b', prompt: (previous) => `got:${previous?.text}` },
    ])) as AnyReport
    expect(prompts[1]).toBe('got:out-seq-0')
    expect((report as { final?: string }).final).toBe('out-seq-1')
  })

  it('relay: draft threads through turns', async () => {
    const inputs: string[] = []
    const execute: TaskExecute = async (task) => {
      inputs.push(task.prompt)
      return { taskId: task.id, status: 'completed', text: `draft-${task.id}`, error: undefined, durationMs: 1, raw: undefined }
    }
    const report = (await runRelay(execute, {
      prompt: 'goal', steps: [{ agentId: 'a' }, { agentId: 'b' }],
    })) as AnyReport & { draft: string }
    expect(inputs[1]).toContain('draft-relay-0')
    expect(report.draft).toBe('draft-relay-1')
  })

  it('sequential failure cascade: dependents cancelled, partial preserved', async () => {
    const execute = executeWith((task) =>
      task.id === 'seq-0'
        ? { status: 'failed', error: 'boom' }
        : { status: 'completed', text: 'should-not-run' })
    const report = (await runSequential(execute, [
      { agentId: 'a', prompt: 'x' },
      { agentId: 'b', prompt: 'y' },
      { agentId: 'c', prompt: 'z' },
    ])) as AnyReport
    expect(report.status).toBe('failed') // nothing completed
    expect(report.tasks[1]!.status).toBe('cancelled')
    expect(report.tasks[1]!.error).toContain("dependency 'seq-0' failed")
    expect(report.metadata).toEqual({ taskCount: 3, completed: 0, failed: 1, cancelled: 2, timedOut: 0 })
  })
})
