import { describe, expect, it } from 'vitest'
import { GraphError, TaskGraph } from '../../src/graph'

function complete(graph: TaskGraph, id: string): void {
  const task = graph.get(id)
  if (!task) throw new Error(`unknown ${id}`)
  task.status = 'completed'
}

describe('TaskGraph', () => {
  it('builds a linear graph and resolves ready() step by step', () => {
    const graph = new TaskGraph()
    graph.add({ id: 'a', agentId: 'w', prompt: 'a' })
    graph.add({ id: 'b', agentId: 'w', prompt: 'b', dependsOn: ['a'] })
    graph.add({ id: 'c', agentId: 'w', prompt: 'c', dependsOn: ['b'] })
    graph.validate()

    expect(graph.size).toBe(3)
    expect(graph.ready().map((t) => t.id)).toEqual(['a'])
    complete(graph, 'a')
    expect(graph.ready().map((t) => t.id)).toEqual(['b'])
    complete(graph, 'b')
    expect(graph.ready().map((t) => t.id)).toEqual(['c'])
  })

  it('reports independent tasks as ready together (parallel)', () => {
    const graph = new TaskGraph()
    graph.add({ id: 'a', agentId: 'w', prompt: 'a' })
    graph.add({ id: 'b', agentId: 'w', prompt: 'b' })
    graph.add({ id: 'c', agentId: 'w', prompt: 'c' })
    expect(graph.ready().map((t) => t.id)).toEqual(['a', 'b', 'c'])
  })

  it('diamond graph: join waits for both branches', () => {
    const graph = new TaskGraph()
    graph.add({ id: 'a', agentId: 'w', prompt: 'a' })
    graph.add({ id: 'b', agentId: 'w', prompt: 'b', dependsOn: ['a'] })
    graph.add({ id: 'c', agentId: 'w', prompt: 'c', dependsOn: ['a'] })
    graph.add({ id: 'd', agentId: 'w', prompt: 'd', dependsOn: ['b', 'c'] })
    graph.validate()

    complete(graph, 'a')
    expect(graph.ready().map((t) => t.id)).toEqual(['b', 'c'])
    // ready() is a pure query: completing b alone does not consume c
    complete(graph, 'b')
    expect(graph.ready().map((t) => t.id)).toEqual(['c'])
    complete(graph, 'c')
    expect(graph.ready().map((t) => t.id)).toEqual(['d'])
    complete(graph, 'd')
    expect(graph.isComplete()).toBe(true)
  })

  it('rejects duplicate ids', () => {
    const graph = new TaskGraph()
    graph.add({ id: 'a', agentId: 'w', prompt: 'a' })
    expect(() => graph.add({ id: 'a', agentId: 'w', prompt: 'a2' })).toThrowError(GraphError)
    try {
      graph.add({ id: 'a', agentId: 'w', prompt: 'a3' })
    } catch (error) {
      expect((error as GraphError).code).toBe('duplicate-id')
    }
  })

  it('rejects missing dependencies on validate()', () => {
    const graph = new TaskGraph()
    graph.add({ id: 'a', agentId: 'w', prompt: 'a', dependsOn: ['ghost'] })
    expect(() => graph.validate()).toThrowError(GraphError)
    try {
      graph.validate()
    } catch (error) {
      expect((error as GraphError).code).toBe('missing-dependency')
      expect((error as GraphError).message).toContain('ghost')
    }
  })

  it('rejects self dependencies', () => {
    const graph = new TaskGraph()
    graph.add({ id: 'a', agentId: 'w', prompt: 'a', dependsOn: ['a'] })
    expect(() => graph.validate()).toThrowError(GraphError)
    try {
      graph.validate()
    } catch (error) {
      expect((error as GraphError).code).toBe('self-dependency')
    }
  })

  it('rejects cycles and names the offending nodes', () => {
    const graph = new TaskGraph()
    graph.add({ id: 'a', agentId: 'w', prompt: 'a', dependsOn: ['c'] })
    graph.add({ id: 'b', agentId: 'w', prompt: 'b', dependsOn: ['a'] })
    graph.add({ id: 'c', agentId: 'w', prompt: 'c', dependsOn: ['b'] })
    let code: string | undefined
    let message = ''
    try {
      graph.validate()
    } catch (error) {
      code = (error as GraphError).code
      message = (error as GraphError).message
    }
    expect(code).toBe('cycle')
    expect(message).toContain('a')
    expect(message).toContain('b')
    expect(message).toContain('c')
  })

  it('dependencies()/dependents() answer queries deterministically', () => {
    const graph = new TaskGraph()
    graph.add({ id: 'a', agentId: 'w', prompt: 'a' })
    graph.add({ id: 'b', agentId: 'w', prompt: 'a' })
    graph.add({ id: 'd', agentId: 'w', prompt: 'd', dependsOn: ['b', 'a'] })
    expect(graph.dependencies('d')).toEqual(['b', 'a'])
    expect(graph.dependents('a')).toEqual(['d'])
    expect(() => graph.dependencies('nope')).toThrowError(GraphError)
  })

  it('ready() only counts completed dependencies, not terminal failures', () => {
    const graph = new TaskGraph()
    graph.add({ id: 'a', agentId: 'w', prompt: 'a' })
    graph.add({ id: 'b', agentId: 'w', prompt: 'b', dependsOn: ['a'] })
    graph.get('a')!.status = 'failed'
    expect(graph.ready().map((t) => t.id)).toEqual([])
  })
})
