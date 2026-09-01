import { describe, expect, it } from 'vitest'
import { apply, type MultiAgentApi } from '../../src/index'
import { createMetricsCollector } from '../../src/observability'
import { createRuntimeDiagnostics, RunRegistry } from '../../src/diagnostics'
import type { DshContext, DshAgentHandle, UserMessage } from '../../src/dsh'

class FakeAgent implements DshAgentHandle {
  readonly id: string
  readonly session = { events: [] as never[] }
  constructor(id: string) { this.id = id }
  followup(_message: UserMessage): void {
    this.session.events.push({
      type: 'assistant/message',
      data: { turn: 1, step: 1, message: { role: 'assistant', content: [{ type: 'text', text: 'ok' }] } },
    } as never)
    this.session.events.push({ type: 'turn/end', data: { turn: 1, reason: { kind: 'completed' } } } as never)
  }
  async whenIdle(): Promise<void> {}
  cancel(): void {}
}

function mount(agents: readonly FakeAgent[], config: Parameters<typeof apply>[1] = {}): MultiAgentApi {
  let api: MultiAgentApi | undefined
  const ctx: DshContext = {
    agents: { get: id => agents.find(agent => agent.id === String(id)) },
    reflect: { provide: (_name, value) => { api = value as MultiAgentApi } },
  }
  apply(ctx, config)
  if (!api) throw new Error('multiAgent service was not provided')
  return api
}

describe('diagnostics public integration', () => {
  it('exposes the injected diagnostics instance and records a recovery run', async () => {
    const metrics = createMetricsCollector()
    const registry = new RunRegistry(8)
    const diagnostics = createRuntimeDiagnostics({ metrics, registry })
    const api = mount([new FakeAgent('agent-1')], { diagnostics })

    expect(api.diagnostics()).toBe(diagnostics)
    const result = await api.runWithRecovery(
      { tasks: [{ id: 'task-1', agentId: 'agent-1', prompt: 'hello' }] },
      { runId: 'r11-api', input: 'hello', agents: [{ id: 'agent-1', capabilities: [] }], recovery: { maxAttempts: 1 } },
    )

    expect(result.status).toBe('completed')
    expect(diagnostics.inspect('r11-api')).toMatchObject({ runId: 'r11-api', status: 'completed', attempts: 1, failureCount: 0 })
    expect(diagnostics.health().activeRuns).toBe(0)
    expect(metrics.snapshot().recoveryCompleted).toBe(1)
  })

  it('delivers each lifecycle event once to the external observer', async () => {
    const events: string[] = []
    const api = mount([new FakeAgent('agent-1')], { observability: event => events.push(event.type) })

    await api.runWithRecovery(
      { tasks: [{ id: 'task-1', agentId: 'agent-1', prompt: 'hello' }] },
      { runId: 'r11-observer', input: 'hello', agents: [{ id: 'agent-1', capabilities: [] }], recovery: { maxAttempts: 1 } },
    )

    expect(events.filter(event => event === 'recovery.started')).toHaveLength(1)
    expect(events.filter(event => event === 'recovery.attempt')).toHaveLength(1)
    expect(events.filter(event => event === 'recovery.finished')).toHaveLength(1)
    expect(events.filter(event => event === 'task.started')).toHaveLength(1)
    expect(events.filter(event => event === 'task.finished')).toHaveLength(1)
  })
})
