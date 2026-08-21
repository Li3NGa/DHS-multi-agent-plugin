import { describe, expect, it } from 'vitest'
import { Task } from '../src/task'

describe('Task', () => {
  it('creates a task from a spec', () => {
    const task = new Task({
      id: 't1',
      agentId: 'researcher',
      prompt: 'find sources',
      dependsOn: ['t0'],
      timeoutMs: 5000,
    })
    expect(task.id).toBe('t1')
    expect(task.agentId).toBe('researcher')
    expect(task.prompt).toBe('find sources')
    expect(task.dependsOn).toEqual(['t0'])
    expect(task.timeoutMs).toBe(5000)
  })

  it('starts pending and exposes status transitions', () => {
    const task = new Task({ id: 't1', agentId: 'a', prompt: 'p' })
    expect(task.status).toBe('pending')
    expect(task.isTerminal).toBe(false)
    task.status = 'ready'
    task.status = 'running'
    expect(task.isTerminal).toBe(false)
    task.status = 'completed'
    expect(task.status).toBe('completed')
    expect(task.isTerminal).toBe(true)
  })

  it('defaults metadata to a frozen empty object', () => {
    const task = new Task({ id: 't1', agentId: 'a', prompt: 'p' })
    expect(task.metadata).toEqual({})
    expect(Object.isFrozen(task.metadata)).toBe(true)
    const withMeta = new Task({ id: 't2', agentId: 'a', prompt: 'p', metadata: { kind: 'step' } })
    expect(withMeta.metadata).toEqual({ kind: 'step' })
  })

  it('rejects malformed specs', () => {
    expect(() => new Task({ id: '', agentId: 'a', prompt: 'p' })).toThrow(TypeError)
    expect(() => new Task({ id: 't', agentId: '', prompt: 'p' })).toThrow(TypeError)
    expect(() => new Task({ id: 't', agentId: 'a', prompt: 'p', timeoutMs: 0 })).toThrow(TypeError)
    expect(() => new Task({ id: 't', agentId: 'a', prompt: 'p', timeoutMs: Number.NaN })).toThrow(TypeError)
    expect(() => new Task({ id: 't', agentId: 'a', prompt: 'p', dependsOn: ['x', 'x'] })).toThrow(TypeError)
  })

  it('withPrompt keeps identity fields', () => {
    const task = new Task({ id: 't1', agentId: 'a', prompt: 'old', dependsOn: ['t0'], timeoutMs: 10 })
    const copy = task.withPrompt('new')
    expect(copy.id).toBe('t1')
    expect(copy.agentId).toBe('a')
    expect(copy.dependsOn).toEqual(['t0'])
    expect(copy.timeoutMs).toBe(10)
    expect(copy.prompt).toBe('new')
  })
})
