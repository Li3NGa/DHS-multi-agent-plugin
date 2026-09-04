import { describe, expect, it, vi } from 'vitest'
import { AgentRunner } from '../../src/runner'
import type { DshAgentHandle, DshContext, UserMessage } from '../../src/dsh'
import { Task } from '../../src/task'

function contextWith(agent: unknown): DshContext {
  return {
    agents: {
      get: (id) => id === 'w' ? agent as DshAgentHandle : undefined,
    },
  }
}

function makeTask(timeoutMs?: number): Task {
  return new Task({ id: 't1', agentId: 'w', prompt: 'hello', timeoutMs })
}

class FollowupThrowingAgent {
  readonly id = 'w'
  readonly events: readonly unknown[] = []
  followup(_message: UserMessage): void {
    throw new Error('followup exploded')
  }
  async whenIdle(): Promise<void> {}
  cancel(): void {}
  get session(): { readonly events: readonly unknown[] } {
    return { events: this.events }
  }
}

class CancelThrowingAgent {
  readonly id = 'w'
  readonly events: readonly unknown[] = []
  #idle = false
  #wake: (() => void) | undefined

  followup(_message: UserMessage): void {
    this.#idle = false
  }

  async whenIdle(): Promise<void> {
    if (!this.#idle) {
      await new Promise<void>((resolve) => {
        this.#wake = resolve
      })
    }
  }

  cancel(): void {
    this.#idle = true
    this.#wake?.()
    throw new Error('cancel exploded')
  }

  get session(): { readonly events: readonly unknown[] } {
    return { events: this.events }
  }
}

describe('AgentRunner exception safety', () => {
  it('turns synchronous followup exceptions into a failed outcome', async () => {
    const agent = new FollowupThrowingAgent()
    const outcome = await new AgentRunner(contextWith(agent)).run(makeTask())

    expect(outcome.status).toBe('failed')
    expect(outcome.error).toBe('followup exploded')
  })

  it('contains cancel exceptions during timeout and still returns the timeout outcome', async () => {
    vi.useFakeTimers()
    try {
      const agent = new CancelThrowingAgent()
      const run = new AgentRunner(contextWith(agent)).run(makeTask(10))
      await vi.advanceTimersByTimeAsync(10)
      const outcome = await run

      expect(outcome.status).toBe('failed')
      expect(outcome.error).toContain('timeout')
    } finally {
      vi.useRealTimers()
    }
  })

  it('contains cancel exceptions during AbortSignal cancellation', async () => {
    const agent = new CancelThrowingAgent()
    const controller = new AbortController()
    const run = new AgentRunner(contextWith(agent)).run(makeTask(), controller.signal)
    controller.abort()
    const outcome = await run

    expect(outcome.status).toBe('cancelled')
    expect(outcome.error).toBe('cancelled')
  })
})
