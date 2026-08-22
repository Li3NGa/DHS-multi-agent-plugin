import { describe, expect, it } from 'vitest'
import { runSequential } from '../../src/strategies/sequential'
import type { TaskExecute } from '../../src/scheduler'
import type { Task } from '../../src/task'

describe('runSequential', () => {
  it('A -> B -> C with each step receiving the previous result', async () => {
    const prompts: Array<{ agentId: string; prompt: string }> = []
    const execute: TaskExecute = async (task: Task) => {
      prompts.push({ agentId: task.agentId, prompt: task.prompt })
      return {
        taskId: task.id,
        status: 'completed',
        text: `${task.agentId}-answer`,
        error: undefined,
        durationMs: 1,
        raw: undefined,
      }
    }
    const report = await runSequential(execute, [
      { agentId: 'a', prompt: 'start' },
      { agentId: 'b', prompt: (previous) => `given: ${previous?.text}` },
      { agentId: 'c', prompt: (previous) => `refined: ${previous?.text}` },
    ])

    expect(prompts.map((p) => p.agentId)).toEqual(['a', 'b', 'c'])
    expect(prompts[0]!.prompt).toBe('start')
    expect(prompts[1]!.prompt).toBe('given: a-answer')
    expect(prompts[2]!.prompt).toBe('refined: b-answer')
    expect(report.ok).toBe(true)
    expect(report.final).toBe('c-answer')
    expect(report.steps.map((s) => s.status)).toEqual(['completed', 'completed', 'completed'])
  })

  it('breaks the chain when a step fails: later steps are cancelled', async () => {
    const seen: string[] = []
    const execute: TaskExecute = async (task) => {
      seen.push(task.id)
      if (task.id === 'seq-1') {
        return { taskId: task.id, status: 'failed', text: undefined, error: 'boom', durationMs: 1, raw: undefined }
      }
      return { taskId: task.id, status: 'completed', text: `${task.id}-ok`, error: undefined, durationMs: 1, raw: undefined }
    }
    const report = await runSequential(execute, [
      { agentId: 'a', prompt: 'p' },
      { agentId: 'b', prompt: (prev) => `x${prev?.index}` },
      { agentId: 'c', prompt: 'p' },
    ])
    expect(seen).toEqual(['seq-0', 'seq-1']) // c never runs
    expect(report.ok).toBe(false)
    expect(report.steps[1]!.status).toBe('failed')
    expect(report.steps[2]!.status).toBe('cancelled')
    expect(report.final).toBe('seq-0-ok')
  })

  it('returns an empty report for zero steps', async () => {
    const report = await runSequential(async (task) => {
      throw new Error('must not run')
    }, [])
    expect(report.steps).toEqual([])
    expect(report.ok).toBe(true)
  })
})
