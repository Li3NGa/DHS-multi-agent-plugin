import { describe, expect, it } from 'vitest'
import { TaskGraph } from '../../src/graph'
import { Scheduler } from '../../src/scheduler'
import type { TaskOutcome } from '../../src/runner'
import type { Task } from '../../src/task'

function outcome(id: string, status: TaskOutcome['status'] = 'completed', error?: string): TaskOutcome {
  return {
    taskId: id,
    status,
    text: status === 'completed' ? `${id}-out` : undefined,
    error,
    durationMs: 1,
    raw: undefined,
  }
}

function gatedPool() {
  const gates = new Map<string, (value: TaskOutcome) => void>()
  const execute = (task: Task): Promise<TaskOutcome> => new Promise((resolve) => {
    gates.set(task.id, resolve)
  })
  return {
    execute,
    started: (id: string) => gates.has(id),
    release: (id: string, value: TaskOutcome = outcome(id)) => {
      const resolve = gates.get(id)
      gates.delete(id)
      resolve?.(value)
    },
    releaseAll: (make: (id: string) => TaskOutcome = (id) => outcome(id)) => {
      for (const [id, resolve] of [...gates]) {
        gates.delete(id)
        resolve(make(id))
      }
    },
  }
}

function tick(): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, 0))
}

describe('Scheduler', () => {
  it('runs a single task to completion', async () => {
    const graph = new TaskGraph()
    graph.add({ id: 'only', agentId: 'w', prompt: 'p' })
    const scheduler = new Scheduler(async (task) => outcome(task.id))
    const report = await scheduler.run(graph)

    expect(report.ok).toBe(true)
    expect(report.results.get('only')?.text).toBe('only-out')
    expect(graph.get('only')?.status).toBe('completed')
  })

  it('runs independent tasks on different agents in parallel', async () => {
    const graph = new TaskGraph()
    graph.add({ id: 'a', agentId: 'w1', prompt: 'p' })
    graph.add({ id: 'b', agentId: 'w2', prompt: 'p' })
    graph.add({ id: 'c', agentId: 'w3', prompt: 'p' })
    const pool = gatedPool()
    const run = new Scheduler(pool.execute).run(graph)

    await tick()
    expect(pool.started('a')).toBe(true)
    expect(pool.started('b')).toBe(true)
    expect(pool.started('c')).toBe(true)

    pool.releaseAll()
    const report = await run
    expect(report.ok).toBe(true)
  })

  it('respects dependency ordering', async () => {
    const graph = new TaskGraph()
    graph.add({ id: 'a', agentId: 'w', prompt: 'p' })
    graph.add({ id: 'b', agentId: 'w', prompt: 'p', dependsOn: ['a'] })
    graph.add({ id: 'c', agentId: 'w', prompt: 'p', dependsOn: ['b'] })
    const pool = gatedPool()
    const started: string[] = []
    const run = new Scheduler((task) => {
      started.push(task.id)
      return pool.execute(task)
    }).run(graph)

    await tick()
    expect(started).toEqual(['a'])
    pool.release('a')
    await tick()
    expect(started).toEqual(['a', 'b'])
    pool.release('b')
    await tick()
    expect(started).toEqual(['a', 'b', 'c'])
    pool.release('c')

    expect((await run).ok).toBe(true)
  })

  it('caps in-flight tasks at the configured concurrency', async () => {
    const graph = new TaskGraph()
    for (let i = 0; i < 6; i += 1) {
      graph.add({ id: `t${i}`, agentId: `w${i}`, prompt: 'p' })
    }

    let inFlight = 0
    let peak = 0
    const pool = gatedPool()
    const scheduler = new Scheduler(async (task) => {
      inFlight += 1
      peak = Math.max(peak, inFlight)
      try {
        return await pool.execute(task)
      } finally {
        inFlight -= 1
      }
    }, { concurrency: 2 })

    const run = scheduler.run(graph)
    for (let guard = 0; guard < 10 && !graph.isComplete(); guard += 1) {
      await tick()
      pool.releaseAll()
    }
    const report = await run

    expect(report.ok).toBe(true)
    expect(peak).toBe(2)
  })

  it('serializes ready tasks targeting the same agent while preserving cross-agent parallelism', async () => {
    const graph = new TaskGraph()
    graph.add({ id: 'a', agentId: 'w', prompt: 'p' })
    graph.add({ id: 'b', agentId: 'w', prompt: 'p' })
    graph.add({ id: 'c', agentId: 'v', prompt: 'p' })
    const pool = gatedPool()
    const started: string[] = []
    const scheduler = new Scheduler((task) => {
      started.push(task.id)
      return pool.execute(task)
    }, { concurrency: 2 })
    const run = scheduler.run(graph)

    await tick()
    expect(started).toEqual(['a', 'c'])
    expect(pool.started('b')).toBe(false)

    pool.release('c')
    await tick()
    expect(started).toEqual(['a', 'c'])
    expect(pool.started('b')).toBe(false)

    pool.release('a')
    await tick()
    expect(started).toEqual(['a', 'c', 'b'])
    expect(pool.started('b')).toBe(true)

    pool.release('b')
    expect((await run).ok).toBe(true)
  })

  it('propagates task failure to dependents as cancelled', async () => {
    const graph = new TaskGraph()
    graph.add({ id: 'a', agentId: 'w', prompt: 'p' })
    graph.add({ id: 'b', agentId: 'w', prompt: 'p', dependsOn: ['a'] })
    graph.add({ id: 'c', agentId: 'w', prompt: 'p', dependsOn: ['b'] })
    graph.add({ id: 'd', agentId: 'v', prompt: 'p' })
    const scheduler = new Scheduler(async (task) => {
      if (task.id === 'a') return outcome(task.id, 'failed', 'boom')
      return outcome(task.id)
    })

    const report = await scheduler.run(graph)
    expect(report.ok).toBe(false)
    expect(report.results.get('a')?.status).toBe('failed')
    expect(report.results.get('b')?.status).toBe('cancelled')
    expect(report.results.get('b')?.error).toContain("dependency 'a' failed")
    expect(report.results.get('c')?.status).toBe('cancelled')
    expect(report.results.get('d')?.status).toBe('completed')
  })

  it('cancels pending and in-flight work on AbortSignal', async () => {
    const graph = new TaskGraph()
    graph.add({ id: 'a', agentId: 'w', prompt: 'p' })
    graph.add({ id: 'b', agentId: 'v', prompt: 'p' })
    const pool = gatedPool()
    const controller = new AbortController()
    const scheduler = new Scheduler(pool.execute)
    const run = scheduler.run(graph, controller.signal)

    await tick()
    expect(pool.started('a')).toBe(true)
    expect(pool.started('b')).toBe(true)
    controller.abort()

    const report = await run
    expect(report.stopped).toBe(true)
    expect(report.ok).toBe(false)
    expect(report.results.get('a')?.status).toBe('cancelled')
    expect(report.results.get('b')?.status).toBe('cancelled')

    pool.release('a', outcome('a'))
    pool.release('b', outcome('b'))
    await tick()
    expect(graph.get('a')?.status).toBe('cancelled')
    expect(graph.get('b')?.status).toBe('cancelled')
  })

  it('cancels the active run through stop()', async () => {
    const graph = new TaskGraph()
    graph.add({ id: 'a', agentId: 'w', prompt: 'p' })
    const pool = gatedPool()
    const scheduler = new Scheduler(pool.execute)
    const run = scheduler.run(graph)

    await tick()
    scheduler.stop()
    const report = await run

    expect(report.stopped).toBe(true)
    expect(report.results.get('a')?.status).toBe('cancelled')
  })

  it('reports completion order separately from insertion order', async () => {
    const graph = new TaskGraph()
    graph.add({ id: 'a', agentId: 'w1', prompt: 'p' })
    graph.add({ id: 'b', agentId: 'w2', prompt: 'p' })
    const pool = gatedPool()
    const run = new Scheduler(pool.execute).run(graph)

    await tick()
    pool.release('b')
    await tick()
    pool.release('a')
    const report = await run

    expect(report.order).toEqual(['b', 'a'])
    expect([...report.results.keys()]).toEqual(['a', 'b'])
    expect(report.ok).toBe(true)
  })

  it('rejects reuse of a previously scheduled graph before executing again', async () => {
    const graph = new TaskGraph()
    graph.add({ id: 'a', agentId: 'w', prompt: 'p' })
    let calls = 0
    const scheduler = new Scheduler(async (task) => {
      calls += 1
      return outcome(task.id)
    })

    await scheduler.run(graph)
    expect(calls).toBe(1)
    expect(graph.get('a')?.status).toBe('completed')

    await expect(scheduler.run(graph)).rejects.toThrow(/cannot be reused after scheduling/)
    expect(calls).toBe(1)
    expect(graph.get('a')?.status).toBe('completed')
  })

  it('rejects invalid graphs and concurrent scheduler runs', async () => {
    const invalid = new TaskGraph()
    invalid.add({ id: 'a', agentId: 'w', prompt: 'p', dependsOn: ['ghost'] })
    const scheduler = new Scheduler(async (task) => outcome(task.id))
    await expect(scheduler.run(invalid)).rejects.toThrow()

    const valid = new TaskGraph()
    valid.add({ id: 'a', agentId: 'w', prompt: 'p' })
    const pool = gatedPool()
    const first = new Scheduler(pool.execute)
    const firstRun = first.run(valid)
    await tick()
    await expect(first.run(valid)).rejects.toThrow(/already running/)
    pool.release('a')
    await firstRun
  })
})
