import { describe, expect, it } from 'vitest'
import { TaskGraph } from '../src/graph'
import { Scheduler } from '../src/scheduler'
import type { TaskOutcome } from '../src/runner'
import type { Task } from '../src/task'
import { deferred, type Deferred } from './helpers'

/** Execute fn that never settles until the test allows it. */
function gatedExecute(): {
  execute: (task: Task, signal: AbortSignal) => Promise<TaskOutcome>
  started: (id: string) => boolean
  release: (id: string, outcome?: TaskOutcome) => void
  releaseAllWith: (make: (id: string) => TaskOutcome) => void
} {
  const gates = new Map<string, { deferred: Deferred<TaskOutcome>; task: Task }>()
  const execute = (task: Task): Promise<TaskOutcome> => {
    const gate = deferred<TaskOutcome>()
    gates.set(task.id, { deferred: gate, task })
    return gate.promise
  }
  return {
    execute,
    started: (id) => gates.has(id),
    release: (id, outcome) => {
      const gate = gates.get(id)
      gates.delete(id)
      gate?.deferred.resolve(outcome ?? {
        taskId: id, status: 'completed', text: `${id}-out`, error: undefined, durationMs: 1, raw: undefined,
      })
    },
    releaseAllWith: (make) => {
      for (const [id, gate] of [...gates]) {
        gates.delete(id)
        gate.deferred.resolve(make(id))
      }
    },
  }
}

function makeOutcome(id: string, status: TaskOutcome['status'], error?: string): TaskOutcome {
  return {
    taskId: id,
    status,
    text: status === 'completed' ? `${id}-out` : undefined,
    error,
    durationMs: 1,
    raw: undefined,
  }
}

describe('Scheduler', () => {
  it('runs a single task to completion', async () => {
    const graph = new TaskGraph()
    graph.add({ id: 'only', agentId: 'w', prompt: 'p' })
    const calls: string[] = []
    const scheduler = new Scheduler(async (task) => {
      calls.push(task.id)
      return makeOutcome(task.id, 'completed')
    })
    const report = await scheduler.run(graph)
    expect(report.ok).toBe(true)
    expect(calls).toEqual(['only'])
    expect(report.results.get('only')?.text).toBe('only-out')
    expect(graph.get('only')?.status).toBe('completed')
  })

  it('runs independent tasks in parallel', async () => {
    const graph = new TaskGraph()
    graph.add({ id: 'a', agentId: 'w', prompt: 'p' })
    graph.add({ id: 'b', agentId: 'w', prompt: 'p' })
    graph.add({ id: 'c', agentId: 'w', prompt: 'p' })
    const pool = gatedExecute()
    const scheduler = new Scheduler(pool.execute)
    const run = scheduler.run(graph)
    // all three must be in flight before any resolves
    await new Promise((r) => setTimeout(r, 0))
    expect(pool.started('a')).toBe(true)
    expect(pool.started('b')).toBe(true)
    expect(pool.started('c')).toBe(true)
    pool.releaseAllWith((id) => makeOutcome(id, 'completed'))
    const report = await run
    expect(report.ok).toBe(true)
  })

  it('respects dependency ordering', async () => {
    const graph = new TaskGraph()
    graph.add({ id: 'a', agentId: 'w', prompt: 'p' })
    graph.add({ id: 'b', agentId: 'w', prompt: 'p', dependsOn: ['a'] })
    graph.add({ id: 'c', agentId: 'w', prompt: 'p', dependsOn: ['b'] })
    const events: string[] = []
    const pool = gatedExecute()
    const scheduler = new Scheduler((task, signal) => {
      events.push(`start:${task.id}`)
      return pool.execute(task, signal)
    })
    const run = scheduler.run(graph)
    await new Promise((r) => setTimeout(r, 0))
    expect(events).toEqual(['start:a'])
    pool.release('a')
    await new Promise((r) => setTimeout(r, 0))
    expect(events).toEqual(['start:a', 'start:b'])
    pool.release('b')
    await new Promise((r) => setTimeout(r, 0))
    expect(events).toEqual(['start:a', 'start:b', 'start:c'])
    pool.release('c')
    const report = await run
    expect(report.ok).toBe(true)
  })

  it('caps in-flight tasks at the configured concurrency', async () => {
    const graph = new TaskGraph()
    for (let i = 0; i < 6; i += 1) graph.add({ id: `t${i}`, agentId: 'w', prompt: 'p' })
    let inflight = 0
    let peak = 0
    const pool = gatedExecute()
    const scheduler = new Scheduler(async (task, signal) => {
      inflight += 1
      peak = Math.max(peak, inflight)
      try {
        return await pool.execute(task, signal)
      } finally {
        inflight -= 1
      }
    }, { concurrency: 2 })
    const run = scheduler.run(graph)
    // drain: keep releasing until the run finishes
    const drain = async () => {
      for (let guard = 0; guard < 20 && graph.size > 0; guard += 1) {
        if (graph.isComplete()) break
        await new Promise((r) => setTimeout(r, 5))
        pool.releaseAllWith((id) => makeOutcome(id, 'completed'))
      }
    }
    await Promise.all([run, drain()])
    const report = await run
    expect(report.ok).toBe(true)
    expect(peak).toBeLessThanOrEqual(2)
    expect(peak).toBe(2)
  })

  it('propagates task failure to dependents as cancelled', async () => {
    const graph = new TaskGraph()
    graph.add({ id: 'a', agentId: 'w', prompt: 'p' })
    graph.add({ id: 'b', agentId: 'w', prompt: 'p', dependsOn: ['a'] })
    graph.add({ id: 'c', agentId: 'w', prompt: 'p', dependsOn: ['b'] })
    graph.add({ id: 'd', agentId: 'w', prompt: 'p' })
    const scheduler = new Scheduler(async (task) =>
      task.id === 'a' ? makeOutcome(task.id, 'failed', 'boom') : makeOutcome(task.id, 'completed'),
    )
    const report = await scheduler.run(graph)
    expect(report.ok).toBe(false)
    expect(report.results.get('a')?.status).toBe('failed')
    expect(report.results.get('b')?.status).toBe('cancelled')
    expect(report.results.get('b')?.error).toContain("dependency 'a' failed")
    expect(report.results.get('c')?.status).toBe('cancelled')
    expect(report.results.get('d')?.status).toBe('completed')
  })

  it('settles a hanging task as failed when its timeout fires (via runner semantics at executor level)', async () => {
    // timeout is enforced by the executor (AgentRunner); the scheduler
    // must accept the failed outcome and keep going
    const graph = new TaskGraph()
    graph.add({ id: 'slow', agentId: 'w', prompt: 'p' })
    graph.add({ id: 'fast', agentId: 'w', prompt: 'p', dependsOn: ['slow'] })
    const scheduler = new Scheduler(async (task) => {
      if (task.id === 'slow') return makeOutcome('slow', 'failed', 'timeout after 10ms')
      return makeOutcome(task.id, 'completed')
    })
    const report = await scheduler.run(graph)
    expect(report.results.get('slow')?.error).toBe('timeout after 10ms')
    expect(report.results.get('fast')?.status).toBe('cancelled')
  })

  it('cancels pending and in-flight work on AbortSignal', async () => {
    const graph = new TaskGraph()
    graph.add({ id: 'a', agentId: 'w', prompt: 'p' })
    graph.add({ id: 'b', agentId: 'w', prompt: 'p', dependsOn: ['a'] })
    const pool = gatedExecute()
    const controller = new AbortController()
    const scheduler = new Scheduler(pool.execute)
    const run = scheduler.run(graph, controller.signal)
    await new Promise((r) => setTimeout(r, 0))
    expect(pool.started('a')).toBe(true)
    controller.abort('user cancelled')
    const report = await run
    expect(report.stopped).toBe(true)
    expect(report.ok).toBe(false)
    expect(report.results.get('a')?.status).toBe('cancelled')
    expect(report.results.get('b')?.status).toBe('cancelled')
    expect(graph.get('a')?.status).toBe('cancelled')
    // late completion of the in-flight task is dropped
    pool.release('a', makeOutcome('a', 'completed'))
    await new Promise((r) => setTimeout(r, 0))
    expect(graph.get('a')?.status).toBe('cancelled')
  })

  it('cancels the active run through stop()', async () => {
    const graph = new TaskGraph()
    graph.add({ id: 'a', agentId: 'w', prompt: 'p' })
    const pool = gatedExecute()
    const scheduler = new Scheduler(pool.execute)
    const run = scheduler.run(graph)
    await new Promise((r) => setTimeout(r, 0))
    scheduler.stop()
    const report = await run
    expect(report.stopped).toBe(true)
    expect(report.results.get('a')?.status).toBe('cancelled')
  })

  it('terminates when every task is terminal and reports completion order', async () => {
    const graph = new TaskGraph()
    graph.add({ id: 'a', agentId: 'w', prompt: 'p' })
    graph.add({ id: 'b', agentId: 'w', prompt: 'p' })
    const pool = gatedExecute()
    const scheduler = new Scheduler(pool.execute)
    const run = scheduler.run(graph)
    await new Promise((r) => setTimeout(r, 0))
    // b finishes first; results must still iterate in insertion order
    pool.release('b')
    await new Promise((r) => setTimeout(r, 0))
    pool.release('a')
    const report = await run
    expect(report.order).toEqual(['b', 'a'])
    expect([...report.results.keys()]).toEqual(['a', 'b'])
    expect(report.ok).toBe(true)
    expect(graph.isComplete()).toBe(true)
  })

  it('rejects concurrent runs and invalid graphs', async () => {
    const graph = new TaskGraph()
    graph.add({ id: 'a', agentId: 'w', prompt: 'p', dependsOn: ['ghost'] })
    const scheduler = new Scheduler(async (task) => makeOutcome(task.id, 'completed'))
    await expect(scheduler.run(graph)).rejects.toThrow()
    const valid = new TaskGraph()
    valid.add({ id: 'a', agentId: 'w', prompt: 'p' })
    const pool = gatedExecute()
    const bounded = new Scheduler(pool.execute)
    const first = bounded.run(valid)
    await new Promise((r) => setTimeout(r, 0))
    await expect(bounded.run(valid)).rejects.toThrow(/already running/)
    pool.release('a')
    await first
  })
})
