/**
 * Runtime API contract tests — freeze enforcement for
 * docs/runtime-api.md. These snapshot the PUBLIC surface and pin the
 * documented semantics of Task / TaskGraph / Scheduler / AgentRunner.
 * They are additive: any change that breaks them is a breaking API change
 * and must bump the documented contract, not the other way round.
 */
import { describe, expect, it } from 'vitest'
import * as api from '../../src/index'
import { Task, TaskStatus, isTerminalStatus } from '../../src/task'
import { GraphError, TaskGraph } from '../../src/graph'
import { Scheduler } from '../../src/scheduler'
import { outcomeFromEvents, type TaskOutcome } from '../../src/runner'

function outcome(taskId: string, status: TaskOutcome['status'], error?: string): TaskOutcome {
  return {
    taskId, status,
    text: status === 'completed' ? `${taskId}-out` : undefined,
    error,
    durationMs: 1,
    raw: undefined,
  }
}

describe('public API surface (docs/runtime-api.md §1)', () => {
  it('exports exactly the frozen value surface', () => {
    expect(Object.keys(api).sort()).toEqual([
      'AgentRunner',
      'DEFAULT_TIMEOUT_MS',
      'GraphError',
      'Scheduler',
      'Task',
      'TaskGraph',
      'apply',
      'inject',
      'runBroadcast',
      'runRelay',
      'runSequential',
    ])
  })

  it('kinds and constants match the contract', () => {
    expect(api.inject).toEqual(['agents'])
    expect(api.DEFAULT_TIMEOUT_MS).toBe(60_000)
    expect(typeof api.apply).toBe('function')
    expect(typeof api.runSequential).toBe('function')
    expect(typeof api.runRelay).toBe('function')
    expect(typeof api.runBroadcast).toBe('function')
    expect(typeof api.AgentRunner).toBe('function')
    expect(typeof api.Scheduler).toBe('function')
    expect(new api.Task({ id: 't', agentId: 'a', prompt: 'p' }).status).toBe('pending')
  })
})

describe('Task contract (§3)', () => {
  it('starts pending; terminal set is exactly completed/failed/cancelled', () => {
    const statuses: TaskStatus[] = ['pending', 'ready', 'running', 'completed', 'failed', 'cancelled']
    expect(statuses.filter(isTerminalStatus).sort()).toEqual(['cancelled', 'completed', 'failed'])
    const task = new Task({ id: 't', agentId: 'a', prompt: 'p' })
    expect(task.status).toBe('pending')
    expect(task.isTerminal).toBe(false)
  })

  it('freezes metadata and preserves identity in withPrompt', () => {
    const task = new Task({
      id: 't', agentId: 'a', prompt: 'old',
      dependsOn: ['x'], timeoutMs: 10, metadata: { k: 'v' },
    })
    expect(Object.isFrozen(task.metadata)).toBe(true)
    const copy = task.withPrompt('new')
    expect([copy.id, copy.agentId, copy.dependsOn, copy.timeoutMs]).toEqual(['t', 'a', ['x'], 10])
    expect(copy.prompt).toBe('new')
    expect(copy.status).toBe('pending')
  })

  it('rejects malformed specs with TypeError', () => {
    expect(() => new Task({ id: '', agentId: 'a', prompt: 'p' })).toThrow(TypeError)
    expect(() => new Task({ id: 't', agentId: '', prompt: 'p' })).toThrow(TypeError)
    expect(() => new Task({ id: 't', agentId: 'a', prompt: 'p', timeoutMs: 0 })).toThrow(TypeError)
    expect(() => new Task({ id: 't', agentId: 'a', prompt: 'p', dependsOn: ['x', 'x'] })).toThrow(TypeError)
  })
})

describe('TaskGraph contract (§4)', () => {
  it('error codes are exact and never silently repair', () => {
    const dup = new TaskGraph()
    dup.add({ id: 'a', agentId: 'w', prompt: 'p' })
    expect(() => dup.add({ id: 'a', agentId: 'w', prompt: 'p' })).toThrowError(GraphError)
    try { dup.add({ id: 'a', agentId: 'w', prompt: 'p' }) } catch (e) {
      expect((e as GraphError).code).toBe('duplicate-id')
    }

    const missing = new TaskGraph()
    missing.add({ id: 'a', agentId: 'w', prompt: 'p', dependsOn: ['ghost'] })
    try { missing.validate() } catch (e) {
      expect((e as GraphError).code).toBe('missing-dependency')
    }

    const self = new TaskGraph()
    self.add({ id: 'a', agentId: 'w', prompt: 'p', dependsOn: ['a'] })
    try { self.validate() } catch (e) {
      expect((e as GraphError).code).toBe('self-dependency')
    }

    const cycle = new TaskGraph()
    cycle.add({ id: 'a', agentId: 'w', prompt: 'p', dependsOn: ['b'] })
    cycle.add({ id: 'b', agentId: 'w', prompt: 'p', dependsOn: ['a'] })
    try { cycle.validate() } catch (e) {
      expect((e as GraphError).code).toBe('cycle')
      expect((e as GraphError).message).toContain('a')
      expect((e as GraphError).message).toContain('b')
    }
  })

  it('queries are pure, ordered, and throw unknown-task as documented', () => {
    const graph = new TaskGraph()
    graph.add({ id: 'a', agentId: 'w', prompt: 'p' })
    graph.add({ id: 'b', agentId: 'w', prompt: 'p', dependsOn: ['a'] })
    expect(graph.tasks().map((t) => t.id)).toEqual(['a', 'b'])
    expect(graph.ready().map((t) => t.id)).toEqual(['a'])
    // pure query: repeated calls do not consume or mutate
    expect(graph.ready().map((t) => t.id)).toEqual(['a'])
    expect(graph.get('a')!.status).toBe('pending')
    graph.get('a')!.status = 'completed'
    expect(graph.ready().map((t) => t.id)).toEqual(['b'])
    expect(graph.isComplete()).toBe(false)
    expect(() => graph.dependencies('nope')).toThrowError(GraphError)
    expect(() => graph.dependents('nope')).toThrowError(GraphError)
    expect(graph.dependents('a')).toEqual(['b'])
  })
})

describe('Scheduler contract (§5)', () => {
  it('results iterate in insertion order regardless of completion order', async () => {
    const graph = new TaskGraph()
    graph.add({ id: 'a', agentId: 'w', prompt: 'p' })
    graph.add({ id: 'b', agentId: 'w', prompt: 'p' })
    const scheduler = new Scheduler(async (task) => {
      // b finishes first
      if (task.id === 'a') await new Promise((r) => setTimeout(r, 5))
      return outcome(task.id, 'completed')
    })
    const report = await scheduler.run(graph)
    expect([...report.results.keys()]).toEqual(['a', 'b'])
    expect(report.order).toEqual(['b', 'a'])
    expect(report.ok).toBe(true)
  })

  it('failure propagation cancels dependents with the documented error text', async () => {
    const graph = new TaskGraph()
    graph.add({ id: 'a', agentId: 'w', prompt: 'p' })
    graph.add({ id: 'b', agentId: 'w', prompt: 'p', dependsOn: ['a'] })
    const scheduler = new Scheduler(async (task) =>
      task.id === 'a' ? outcome('a', 'failed', 'boom') : outcome(task.id, 'completed'),
    )
    const report = await scheduler.run(graph)
    expect(report.results.get('b')?.status).toBe('cancelled')
    expect(report.results.get('b')?.error).toBe("dependency 'a' failed")
    expect(report.ok).toBe(false)
  })

  it('stop() settles as stopped with every remaining task cancelled', async () => {
    const graph = new TaskGraph()
    graph.add({ id: 'hang', agentId: 'w', prompt: 'p' })
    const scheduler = new Scheduler(() => new Promise<TaskOutcome>(() => {}))
    const run = scheduler.run(graph)
    queueMicrotask(() => scheduler.stop())
    const report = await run
    expect(report.stopped).toBe(true)
    expect(report.ok).toBe(false)
    expect(report.results.get('hang')?.status).toBe('cancelled')
  })

  it('guards: double run and invalid concurrency/options', async () => {
    const graph = new TaskGraph()
    graph.add({ id: 'a', agentId: 'w', prompt: 'p' })
    expect(() => new Scheduler(async (t) => outcome(t.id, 'completed'), { concurrency: 0 })).toThrow(TypeError)
    const scheduler = new Scheduler(() => new Promise<TaskOutcome>(() => {}))
    const first = scheduler.run(graph)
    await expect(scheduler.run(graph)).rejects.toThrow(/already running/)
    scheduler.stop()
    await first
  })

  it('execute exceptions become failed outcomes, not run aborts', async () => {
    const graph = new TaskGraph()
    graph.add({ id: 'bad', agentId: 'w', prompt: 'p' })
    graph.add({ id: 'good', agentId: 'w', prompt: 'p' })
    const scheduler = new Scheduler(async (task) => {
      if (task.id === 'bad') throw new Error('executor exploded')
      return outcome(task.id, 'completed')
    })
    const report = await scheduler.run(graph)
    expect(report.results.get('bad')?.status).toBe('failed')
    expect(report.results.get('bad')?.error).toBe('executor exploded')
    expect(report.results.get('good')?.status).toBe('completed')
  })
})

describe('AgentRunner outcome mapping contract (§7–§10)', () => {
  const base = { cancelledBySignal: false, timedOut: false, durationMs: 5 }
  const events = (reason: unknown, text = 'hello') => [
    { type: 'assistant/message', data: { turn: 1, step: 1, message: { role: 'assistant', content: [{ type: 'text', text }] } } },
    { type: 'turn/end', data: { turn: 1, reason } },
  ] as never

  it('completed / timeout / signal-cancel / aborted map exactly as documented', () => {
    const ok = outcomeFromEvents('t', events({ kind: 'completed' }), base)
    expect([ok.status, ok.text, ok.error]).toEqual(['completed', 'hello', undefined])

    const timedOut = outcomeFromEvents('t', events({ kind: 'aborted', reason: { kind: 'hook', reason: 'r' } }), { ...base, timedOut: true })
    expect(timedOut.status).toBe('failed')
    expect(timedOut.error).toContain('timeout:')
    expect(timedOut.text).toBe('hello') // interrupted/partial preserved

    const cancelled = outcomeFromEvents('t', events({ kind: 'aborted', reason: { kind: 'hook', reason: 'r' } }), { ...base, cancelledBySignal: true })
    expect([cancelled.status, cancelled.error]).toEqual(['cancelled', 'cancelled'])

    const error = outcomeFromEvents('t', events({ kind: 'error', error: { message: 'provider down', code: 'X' } }), base)
    expect([error.status, error.error]).toEqual(['failed', 'provider down'])
  })

  it('blocked / max-tokens / empty windows are failures with reason text', () => {
    expect(outcomeFromEvents('t', events({ kind: 'blocked' }), base).error).toBe('turn ended: blocked')
    expect(outcomeFromEvents('t', events({ kind: 'max-tokens' }), base).error).toBe('turn ended: max-tokens')
    expect(outcomeFromEvents('t', [], base).error).toBe('turn ended: no turn/end')
  })

  it('raw counts the turn activity exposed to strategies', () => {
    const result = outcomeFromEvents('t', [
      { type: 'assistant/message', data: { message: { content: [{ type: 'text', text: 'a' }] } } },
      { type: 'tool/call', data: {} },
      { type: 'tool/result', data: {} },
      { type: 'turn/end', data: { reason: { kind: 'completed' } } },
    ] as never, base)
    expect(result.raw).toEqual({ assistantMessages: 1, toolCalls: 1, toolResults: 1, turnEndReason: 'completed' })
  })
})
