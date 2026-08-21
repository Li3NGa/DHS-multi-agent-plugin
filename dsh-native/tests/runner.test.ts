import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { AgentRunner, normalizeReply } from '../src/runner'
import { Task } from '../src/task'
import type { DshAgent, DshContext } from '../src/dsh'

function contextWith(agents: Record<string, DshAgent | undefined>): DshContext {
  return {
    agents: { get: (id) => agents[id] },
    on: () => undefined,
  }
}

function agentOf(
  followup: DshAgent['followup'],
  whenIdle?: DshAgent['whenIdle'],
): DshAgent {
  return { id: 'x', followup, ...(whenIdle ? { whenIdle } : {}) }
}

const task = (spec: Partial<ConstructorParameters<typeof Task>[0]> = {}) =>
  new Task({ id: 't1', agentId: 'w', prompt: 'hello', ...spec })

describe('AgentRunner', () => {
  it('completes a normal response', async () => {
    const followup = vi.fn(async () => 'answer')
    const ctx = contextWith({ w: agentOf(followup) })
    const outcome = await new AgentRunner(ctx).run(task())
    expect(outcome.status).toBe('completed')
    expect(outcome.text).toBe('answer')
    expect(followup).toHaveBeenCalledWith('hello')
    expect(outcome.durationMs).toBeGreaterThanOrEqual(0)
  })

  it('fails with a clear error when the agent is missing', async () => {
    const ctx = contextWith({})
    const outcome = await new AgentRunner(ctx).run(task())
    expect(outcome.status).toBe('failed')
    expect(outcome.error).toBe("agent 'w' not found")
  })

  it('fails when followup rejects', async () => {
    const ctx = contextWith({ w: agentOf(async () => { throw new Error('provider down') }) })
    const outcome = await new AgentRunner(ctx).run(task())
    expect(outcome.status).toBe('failed')
    expect(outcome.error).toBe('provider down')
  })

  it('joins multiple assistant events into one text', async () => {
    const reply = [
      { role: 'user', content: 'hello' },
      { role: 'assistant', content: 'part 1' },
      { role: 'assistant', content: 'part 2' },
      { type: 'tool_result', content: 'ignored' },
    ]
    const ctx = contextWith({ w: agentOf(async () => reply) })
    const outcome = await new AgentRunner(ctx).run(task())
    expect(outcome.status).toBe('completed')
    expect(outcome.text).toBe('part 1\n\npart 2')
    expect(outcome.raw).toBe(reply)
  })

  it('awaits whenIdle() after followup when present', async () => {
    const order: string[] = []
    const ctx = contextWith({
      w: agentOf(
        async () => {
          order.push('followup')
          return 'ok'
        },
        async () => {
          order.push('whenIdle')
        },
      ),
    })
    const outcome = await new AgentRunner(ctx).run(task())
    expect(order).toEqual(['followup', 'whenIdle'])
    expect(outcome.text).toBe('ok')
  })

  describe('timeout', () => {
    beforeEach(() => vi.useFakeTimers())
    afterEach(() => vi.useRealTimers())

    it('fails the task after timeoutMs while the call keeps floating', async () => {
      const ctx = contextWith({ w: agentOf(() => new Promise(() => {})) })
      const runPromise = new AgentRunner(ctx).run(task({ timeoutMs: 50 }))
      await vi.advanceTimersByTimeAsync(60)
      const outcome = await runPromise
      expect(outcome.status).toBe('failed')
      expect(outcome.error).toBe('timeout after 50ms')
    })

    it('uses defaultTimeoutMs from options when the task has none', async () => {
      const ctx = contextWith({ w: agentOf(() => new Promise(() => {})) })
      const runPromise = new AgentRunner(ctx, { defaultTimeoutMs: 30 }).run(task())
      await vi.advanceTimersByTimeAsync(40)
      const outcome = await runPromise
      expect(outcome.status).toBe('failed')
      expect(outcome.error).toBe('timeout after 30ms')
    })
  })

  it('cancels before start when the signal is already aborted', async () => {
    const followup = vi.fn(async () => 'late')
    const ctx = contextWith({ w: agentOf(followup) })
    const controller = new AbortController()
    controller.abort()
    const outcome = await new AgentRunner(ctx).run(task(), controller.signal)
    expect(outcome.status).toBe('cancelled')
    expect(followup).not.toHaveBeenCalled()
  })

  it('cancels mid-flight when the signal aborts', async () => {
    const ctx = contextWith({ w: agentOf(() => new Promise(() => {})) })
    const controller = new AbortController()
    const runPromise = new AgentRunner(ctx).run(task(), controller.signal)
    queueMicrotask(() => controller.abort())
    const outcome = await runPromise
    expect(outcome.status).toBe('cancelled')
    expect(outcome.error).toBe('cancelled')
  })
})

describe('normalizeReply', () => {
  it('handles the documented shapes', () => {
    expect(normalizeReply('plain')).toBe('plain')
    expect(normalizeReply({ content: 'boxed' })).toBe('boxed')
    expect(normalizeReply({ text: 'texted' })).toBe('texted')
    expect(normalizeReply([{ role: 'assistant', content: 'a' }, { role: 'assistant', content: 'b' }])).toBe('a\n\nb')
    expect(normalizeReply(42)).toBe('42')
  })
})
