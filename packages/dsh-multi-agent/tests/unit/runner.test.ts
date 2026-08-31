import { describe, expect, it, vi } from 'vitest'
import { AgentRunner, outcomeFromEvents } from '../../src/runner'
import { Task } from '../../src/task'
import type { DshAgentHandle, DshContext, UserMessage } from '../../src/dsh'

/**
 * Unit-level runner tests over fake agents that follow the REAL DSH API
 * shape: followup() is void, results come from session.events, cancel()
 * stops the turn. Real-harness verification lives in the package smoke
 * and integration suites.
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
