import { describe, expect, it, vi } from 'vitest'
import { AgentRunner, outcomeFromEvents } from '../src/runner'
import { Task } from '../src/task'
import type { DshAgentHandle, DshContext, UserMessage } from '../src/dsh'

/**
 * Unit-level runner tests over fake agents that follow the REAL DSH API
 * shape: followup() is void, results come from session.events, cancel()
 * stops the turn. The real-harness verification lives in dsh-native/smoke
 * (real AgentLoop + real sessions + scripted LLM adapter).
 */

interface ScriptedTurn {
  /** Events appended (in order) once followup() is called. */
  readonly events: unknown[]
}

class FakeAgent {
  readonly id: string
  readonly events: unknown[] = []
  readonly prompts: string[] = []
  readonly cancels: string[] = []
  #script: ScriptedTurn | undefined
  #idle = true

  constructor(id: string, script?: ScriptedTurn) {
    this.id = id
    this.#script = script
  }

  get session(): { readonly events: readonly unknown[] } {
    return { events: this.events }
  }

  followup(message: UserMessage): void {
    this.prompts.push(String(message.content[0] && (message.content[0] as { text?: string }).text))
    this.#idle = false
    if (this.#script) {
      for (const event of this.#script.events) this.events.push(event)
      this.#script = undefined
      this.#idle = true
    }
    // with no script the turn stays open until cancel() or forever
  }

  async whenIdle(): Promise<void> {
    if (!this.#idle) await new Promise<void>(() => {})
  }

  cancel(cause: { kind: string; reason?: string }): void {
    this.cancels.push(cause.reason ?? cause.kind)
    this.#idle = true
    this.events.push(
      { type: 'assistant/message', data: { turn: 1, step: 1, message: { role: 'assistant', content: [{ type: 'text', text: 'partial' }] }, interrupted: true } },
      { type: 'turn/end', data: { turn: 1, reason: { kind: 'aborted', reason: { kind: 'hook', reason: cause.reason ?? 'hook' } } } },
    )
  }
}

function contextWith(...agents: FakeAgent[]): DshContext {
  return {
    agents: {
      get: (id) =>
        agents.find((agent) => agent.id === (id as unknown as string)) as
          | DshAgentHandle
          | undefined,
    },
  }
}

const task = (spec: Partial<ConstructorParameters<typeof Task>[0]> = {}) =>
  new Task({ id: 't1', agentId: 'w', prompt: 'hello', ...spec })

function completedTurn(text: string): ScriptedTurn {
  return {
    events: [
      { type: 'turn/start', data: { turn: 1 } },
      { type: 'assistant/message', data: { turn: 1, step: 1, message: { role: 'assistant', content: [{ type: 'text', text }] } } },
      { type: 'turn/end', data: { turn: 1, reason: { kind: 'completed' } } },
    ],
  }
}

describe('AgentRunner (real API shape)', () => {
  it('completes from session events: followup is void, text comes from assistant/message', async () => {
    const agent = new FakeAgent('w', completedTurn('the answer'))
    const outcome = await new AgentRunner(contextWith(agent)).run(task())
    expect(outcome.status).toBe('completed')
    expect(outcome.text).toBe('the answer')
    expect(agent.prompts).toEqual(['hello'])
    expect(outcome.raw?.turnEndReason).toBe('completed')
  })

  it('fails with a clear error when the agent is missing', async () => {
    const outcome = await new AgentRunner(contextWith()).run(task())
    expect(outcome.status).toBe('failed')
    expect(outcome.error).toBe("agent 'w' not found")
  })

  it('fails when the turn ends with an error reason', async () => {
    const agent = new FakeAgent('w', {
      events: [
        { type: 'turn/end', data: { turn: 1, reason: { kind: 'error', error: { message: 'provider down', code: 'X' } } } },
      ],
    })
    const outcome = await new AgentRunner(contextWith(agent)).run(task())
    expect(outcome.status).toBe('failed')
    expect(outcome.error).toBe('provider down')
  })

  it('joins multiple assistant messages and counts tool activity', async () => {
    const agent = new FakeAgent('w', {
      events: [
        { type: 'assistant/message', data: { turn: 1, step: 1, message: { role: 'assistant', content: [{ type: 'text', text: 'part 1' }] } } },
        { type: 'tool/call', data: { turn: 1, step: 1, callId: 'c1', name: 'fs.read', arguments: '{}' } },
        { type: 'tool/result', data: { turn: 1, step: 1, message: { role: 'user', content: [] } } },
        { type: 'assistant/message', data: { turn: 1, step: 2, message: { role: 'assistant', content: [{ type: 'text', text: 'part 2' }] } } },
        { type: 'turn/end', data: { turn: 1, reason: { kind: 'completed' } } },
      ],
    })
    const outcome = await new AgentRunner(contextWith(agent)).run(task())
    expect(outcome.text).toBe('part 1\n\npart 2')
    expect(outcome.raw).toEqual({ assistantMessages: 2, toolCalls: 1, toolResults: 1, turnEndReason: 'completed' })
  })

  it('times out via the host cancel mechanism and keeps the interrupted prefix', async () => {
    vi.useFakeTimers()
    try {
      const agent = new FakeAgent('w') // never completes on its own
      const runPromise = new AgentRunner(contextWith(agent)).run(task({ timeoutMs: 50 }))
      await vi.advanceTimersByTimeAsync(60)
      const outcome = await runPromise
      expect(outcome.status).toBe('failed')
      expect(outcome.error).toContain('timeout')
      expect(agent.cancels).toHaveLength(1)
      expect(outcome.text).toBe('partial') // interrupted assistant/message
    } finally {
      vi.useRealTimers()
    }
  })

  it('uses defaultTimeoutMs when the task has none', async () => {
    vi.useFakeTimers()
    try {
      const agent = new FakeAgent('w')
      const runPromise = new AgentRunner(contextWith(agent), { defaultTimeoutMs: 30 }).run(task())
      await vi.advanceTimersByTimeAsync(40)
      const outcome = await runPromise
      expect(outcome.status).toBe('failed')
      expect(outcome.error).toContain('timeout')
    } finally {
      vi.useRealTimers()
    }
  })

  it('cancels before start when the signal is already aborted', async () => {
    const agent = new FakeAgent('w', completedTurn('late'))
    const controller = new AbortController()
    controller.abort()
    const outcome = await new AgentRunner(contextWith(agent)).run(task(), controller.signal)
    expect(outcome.status).toBe('cancelled')
    expect(agent.prompts).toEqual([]) // followup never called
  })

  it('cancels mid-turn through agent.cancel when the signal aborts', async () => {
    const agent = new FakeAgent('w') // hangs until cancelled
    const controller = new AbortController()
    const runPromise = new AgentRunner(contextWith(agent)).run(task(), controller.signal)
    queueMicrotask(() => controller.abort())
    const outcome = await runPromise
    expect(outcome.status).toBe('cancelled')
    expect(agent.cancels).toHaveLength(1)
  })
})

describe('outcomeFromEvents', () => {
  it('maps turn/end reasons deterministically', () => {
    const base = { cancelledBySignal: false, timedOut: false, durationMs: 1 }
    const completed = outcomeFromEvents('t', [
      { type: 'turn/end', data: { reason: { kind: 'completed' } } },
    ] as never, base)
    expect(completed.status).toBe('completed')

    const blocked = outcomeFromEvents('t', [
      { type: 'turn/end', data: { reason: { kind: 'blocked' } } },
    ] as never, base)
    expect(blocked.status).toBe('failed')
    expect(blocked.error).toBe('turn ended: blocked')

    const noTurn = outcomeFromEvents('t', [], base)
    expect(noTurn.status).toBe('failed')
    expect(noTurn.error).toBe('turn ended: no turn/end')
  })
})
