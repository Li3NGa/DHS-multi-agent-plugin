import { describe, expect, it } from 'vitest'
import { Scheduler } from '../src/scheduler'
import { TaskGraph } from '../src/graph'
import { Task } from '../src/task'

function task(id: string, agentId = `agent-${id}`, dependsOn: string[] = []): Task {
  return new Task({ id, agentId, prompt: id, ...(dependsOn.length > 0 ? { dependsOn } : {}) })
}

function outcome(id: string) {
  return { taskId: id, status: 'completed' as const, text: id, error: undefined, durationMs: 1, raw: undefined }
}

describe('Scheduler observability', () => {
  it('emits a complete lifecycle with a stable run id', async () => {
    const events: string[] = []
    const scheduler = new Scheduler(async (t) => outcome(t.id), {
      observer: { onEvent: (event) => events.push(`${event.kind}:${event.runId}:${event.taskId ?? ''}`) },
    })
    const graph = new TaskGraph([task('a'), task('b', 'agent-b', ['a'])])
    const report = await scheduler.run(graph)

    expect(report.ok).toBe(true)
    expect(report.runId).toMatch(/^run-/)
    expect(events[0]).toBe(`run.started:${report.runId}:`)
    expect(events.filter((event) => event.startsWith(`task.started:${report.runId}:`))).toHaveLength(2)
    expect(events.filter((event) => event.startsWith(`task.completed:${report.runId}:`))).toHaveLength(2)
    expect(events.at(-1)).toBe(`run.completed:${report.runId}:`)
  })

  it('contains failure details without letting observer exceptions affect execution', async () => {
    const scheduler = new Scheduler(async (t) => {
      if (t.id === 'bad') return { ...outcome(t.id), status: 'failed' as const, error: 'boom' }
      return outcome(t.id)
    }, { observer: { onEvent: () => { throw new Error('telemetry sink down') } } })
    const graph = new TaskGraph([task('bad')])
    const report = await scheduler.run(graph)

    expect(report.ok).toBe(false)
    expect(report.results.get('bad')?.error).toBe('boom')
  })

  it('emits blocked events for dependency cascades', async () => {
    const kinds: string[] = []
    const scheduler = new Scheduler(async (t) => ({ ...outcome(t.id), status: 'failed' as const, error: 'root failure' }), {
      observer: { onEvent: (event) => kinds.push(event.kind) },
    })
    const graph = new TaskGraph([task('root'), task('child', 'agent-child', ['root'])])
    await scheduler.run(graph)

    expect(kinds).toContain('task.failed')
    expect(kinds).toContain('task.blocked')
    expect(kinds).toContain('run.completed')
  })
})
