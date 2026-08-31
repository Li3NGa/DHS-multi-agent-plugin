import { describe, expect, it } from 'vitest'
import { apply, type MultiAgentApi } from '../../src/index'
import type { DshContext, DshAgentHandle, UserMessage } from '../../src/dsh'

class FakeAgent implements DshAgentHandle {
  readonly id: string
  readonly session = { events: [] as never[] }
  constructor(id: string) {
    this.id = id
  }

  followup(_message: UserMessage): void {
    this.session.events.push({
      type: 'assistant/message',
      data: {
        turn: 1,
        step: 1,
        message: { role: 'assistant', content: [{ type: 'text', text: 'recovered' }] },
      },
    } as never)
    this.session.events.push({
      type: 'turn/end',
      data: { turn: 1, reason: { kind: 'completed' } },
    } as never)
  }

  async whenIdle(): Promise<void> {}
  cancel(): void {}
}

function mountedApi(agents: readonly FakeAgent[]): MultiAgentApi {
  let api: MultiAgentApi | undefined
  const ctx: DshContext = {
    agents: {
      get: (id) => agents.find((agent) => agent.id === String(id)) as DshAgentHandle | undefined,
    },
    reflect: {
      provide: (_name, value) => {
        api = value as MultiAgentApi
      },
    },
  }
  apply(ctx)
  if (api === undefined) throw new Error('multiAgent service was not provided')
  return api
}

describe('public recovery entrypoint', () => {
  it('repairs an unavailable explicit agent and reroutes to the remaining pool', async () => {
    const api = mountedApi([new FakeAgent('y')])

    const result = await api.runWithRecovery(
      { tasks: [{ id: 'a', agentId: 'x', prompt: 'hello' }] },
      {
        runId: 'r4-public-repair',
        input: 'hello',
        agents: [{ id: 'x', capabilities: [] }, { id: 'y', capabilities: [] }],
        recovery: { maxAttempts: 3 },
      },
    )

    expect(result.status).toBe('completed')
    expect(result.attempts).toBe(2)
    expect(result.repairsUsed).toBe(1)
    expect(result.decisions).toEqual(['repair', 'completed'])
    expect(result.lastResult?.report.strategy).toBe('sequential')
  })

  it('keeps the plugin-level recovery policy when no per-run override is supplied', async () => {
    const agents = [new FakeAgent('x')]
    let api: MultiAgentApi | undefined
    const ctx: DshContext = {
      agents: {
        get: (id) => agents.find((agent) => agent.id === String(id)) as DshAgentHandle | undefined,
      },
      reflect: {
        provide: (_name, value) => { api = value as MultiAgentApi },
      },
    }
    apply(ctx, { recovery: { maxAttempts: 1 } })
    const result = await api!.runWithRecovery(
      { tasks: [{ id: 'x', prompt: 'ok' }] },
      {
        runId: 'r4-policy',
        input: 'ok',
        agents: [{ id: 'x', capabilities: [] }],
      },
    )

    expect(result.status).toBe('completed')
    expect(result.attempts).toBe(1)
  })
})
