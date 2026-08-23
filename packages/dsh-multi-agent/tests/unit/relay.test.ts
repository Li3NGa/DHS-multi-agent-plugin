import { describe, expect, it } from 'vitest'
import { runRelay, relayMessage } from '../../src/strategies/relay'
import type { TaskExecute } from '../../src/scheduler'
import type { Task } from '../../src/task'

function outcome(task: Task, text: string) {
  return { taskId: task.id, status: 'completed' as const, text, error: undefined, durationMs: 1, raw: undefined }
}

describe('runRelay', () => {
  it('threads the draft: A result -> B -> C without touching any session', async () => {
    const inputs: Array<{ agentId: string; prompt: string }> = []
    const execute: TaskExecute = async (task) => {
      inputs.push({ agentId: task.agentId, prompt: task.prompt })
      return outcome(task, `draft-from-${task.agentId}`)
    }
    const report = await runRelay(execute, {
      prompt: 'write a haiku',
      steps: [{ agentId: 'a' }, { agentId: 'b' }, { agentId: 'c' }],
    })

    // every agent sees the original prompt plus the current draft
    expect(inputs).toHaveLength(3)
    expect(inputs[0]!.prompt).toContain('write a haiku')
    expect(inputs[0]!.prompt).toContain('write a haiku') // draft == prompt initially
    expect(inputs[1]!.prompt).toContain('draft-from-a')
    expect(inputs[2]!.prompt).toContain('draft-from-b')
    // no agent ever saw a later draft (no shared mutable context)
    expect(inputs[1]!.prompt).not.toContain('draft-from-b')

    expect(report.ok).toBe(true)
    expect(report.draft).toBe('draft-from-c')
    expect(report.turns.map((t) => t.agentId)).toEqual(['a', 'b', 'c'])
    expect(report.turns[1]!.output).toBe('draft-from-b')
  })

  it('keeps the last good draft when a turn fails and cancels the rest', async () => {
    const seen: string[] = []
    const execute: TaskExecute = async (task) => {
      seen.push(task.id)
      if (task.id === 'relay-1') {
        return { taskId: task.id, status: 'failed' as const, text: undefined, error: 'stuck', durationMs: 1, raw: undefined }
      }
      return outcome(task, `ok-${task.id}`)
    }
    const report = await runRelay(execute, {
      prompt: 'p',
      steps: [{ agentId: 'a' }, { agentId: 'b' }, { agentId: 'c' }],
    })
    expect(seen).toEqual(['relay-0', 'relay-1'])
    expect(report.draft).toBe('ok-relay-0')
    expect(report.turns[2]!.status).toBe('cancelled')
  })

  it('supports per-step instruction overrides via relayMessage', () => {
    const message = relayMessage({ step: 1, prompt: 'goal', draft: 'current' }, 'IMPROVE')
    expect(message).toContain('goal')
    expect(message).toContain('current')
    expect(message).toContain('IMPROVE')
  })
})
