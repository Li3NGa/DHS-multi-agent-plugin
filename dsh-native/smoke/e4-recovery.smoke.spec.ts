/**
 * Phase E4 — Recovery real-DSH smoke (4 scenarios).
 *
 * Every success path goes through the FULL chain on the real harness:
 *
 *   RecoveryManager -> validate/route -> Supervisor
 *     -> frozen Strategy -> Scheduler -> AgentRunner -> Real DSH
 *
 * Isolation model: each scenario boots its OWN harness with a scenario-local
 * adapter that intercepts turns BY USER-TEXT MARKER (the agent-loop issues
 * auxiliary model calls, so positional FIFO scripting is unreliable here).
 * Nothing is mocked except the model endpoint, matching the repo convention.
 *
 * Alignment rule learned here: the recovery POOL, the real agent REGISTRY
 * and the plan's explicit agentIds must agree per scenario, otherwise the
 * exercise targets validator/router behaviour instead of recovery.
 *
 * Failure injection:
 *   - timeout    : marker turn hangs until the runner cancels it
 *   - unavailable: an agent IS in the pool but absent from the registry
 *   - replan     : marker turn finishes with an error reason -> dep cascade
 *   - cancel     : external AbortSignal during a hanging turn
 */
import { afterAll, describe, expect, it } from 'vitest'
import { Context } from '@deepseek-ai/cordis'
import { LlmAdapter } from '@deepseek-ai/dsh-llm'
import type { GenerateOptions, StreamChunk } from '@deepseek-ai/dsh-llm'
import { AgentRunner } from '../src/runner'
import type { TaskExecute } from '../src/scheduler'
import { createSupervisor } from '../src/supervisor'
import { createRecoveryManager } from '../src/recovery'
import type { RecoveryRunResult } from '../src/recovery'
import { textResponse } from './support'

// ---------- scenario-local adapter ----------

function lastUserText(options: GenerateOptions): string {
  for (let index = options.messages.length - 1; index >= 0; index -= 1) {
    const message = options.messages[index]!
    if (message.role !== 'user') continue
    const parts: string[] = []
    for (const block of message.content) {
      if (block.type === 'text') parts.push(block.text)
    }
    if (parts.length > 0) return parts.join('')
  }
  return ''
}

async function* hangUntilAborted(signal: AbortSignal | undefined): AsyncIterable<StreamChunk> {
  yield { type: 'block-start', index: 0, blockType: 'text' }
  yield { type: 'text-delta', index: 0, text: 'partial' }
  await new Promise<void>((_resolve, reject) => {
    if (signal?.aborted) {
      reject(new Error('aborted'))
      return
    }
    signal?.addEventListener('abort', () => reject(new Error('aborted')), { once: true })
  })
}

type Mode = 'echo' | 'hang-once' | 'error-once'

class E4Adapter extends LlmAdapter {
  private fired = false

  constructor(
    private readonly marker: string,
    private readonly mode: Mode,
  ) {
    super()
  }

  override resolveModel(provider: string, model: string) {
    return Promise.resolve({ provider, id: model, name: model })
  }

  override async *stream(options: GenerateOptions): AsyncIterable<StreamChunk> {
    const text = lastUserText(options)
    if (!this.fired && text.includes(this.marker)) {
      this.fired = true
      if (this.mode === 'hang-once') {
        yield* hangUntilAborted(options.signal)
        return
      }
      // error-once: partial output, then an errored finish reason
      yield { type: 'block-start', index: 0, blockType: 'text' }
      yield { type: 'text-delta', index: 0, text: 'partial ' }
      yield { type: 'usage', usage: { inputTokens: 5, outputTokens: 7 } }
      yield {
        type: 'finish',
        reason: { kind: 'error', error: { message: 'E4 scripted failure' } },
      } as unknown as StreamChunk
      return
    }
    yield* textResponse(text)
  }
}

// ---------- harness helpers ----------

const disposables: (() => Promise<void> | void)[] = []

interface Scenario {
  manager: ReturnType<typeof createRecoveryManager>
  registerAgent(id: string): void
}

async function bootScenario(
  marker: string,
  mode: Mode,
  pool: readonly { id: string; capabilities: readonly string[] }[],
  policy: { maxAttempts?: number; maxReplans?: number },
): Promise<Scenario> {
  const adapter = new E4Adapter(marker, mode)
  const ctx = new Context()
  const LlmRuntime = (await import('@deepseek-ai/dsh-llm')).default
  const SessionStore = (await import('@deepseek-ai/dsh-session')).default
  const SystemPrompt = (await import('@deepseek-ai/dsh-system-prompt')).default
  const ToolRuntime = (await import('@deepseek-ai/dsh-tools')).default
  const AgentRegistry = (await import('@deepseek-ai/dsh-agent')).default
  const AgentLoop = (await import('@deepseek-ai/dsh-agent-loop')).default
  const { SessionId } = await import('@deepseek-ai/dsh-session')

  await ctx.plugin(LlmRuntime)
  await ctx.plugin(SessionStore)
  await ctx.plugin(SystemPrompt)
  await ctx.plugin(ToolRuntime)
  await ctx.plugin(AgentRegistry)
  await ctx.plugin(AgentLoop, { agents: [] as never })
  ctx.llm.registerAdapter(['mock'], adapter)

  disposables.push(() => (ctx as unknown as { dispose?: () => Promise<void> }).dispose?.())

  const runner = new AgentRunner(ctx)
  const execute: TaskExecute = (task, signal) => runner.run(task, signal)
  const supervisor = createSupervisor({ execute })
  const manager = createRecoveryManager({ supervisor, agents: pool, policy })
  return {
    manager,
    registerAgent(id: string): void {
      // only ids registered HERE are executable by the real AgentRunner
      if (pool.some((agent) => agent.id === id)) {
        ctx.agentLoop.create(SessionId(id), { provider: 'mock', model: 'mock' })
      }
    },
  }
}

afterAll(async () => {
  for (const dispose of disposables.splice(0)) await dispose()
})

function sequentialReport(result: RecoveryRunResult) {
  if (result.lastResult === undefined) throw new Error('no supervisor result')
  if (result.lastResult.report.strategy !== 'sequential') {
    throw new Error('expected sequential report')
  }
  return result.lastResult.report.report
}

// ---------- scenarios ----------

describe('E4 recovery — real DSH integration', () => {
  it('S1: task timeout -> retry -> successful execution', async () => {
    const { manager, registerAgent } = await bootScenario(
      'S1-MARKER',
      'hang-once',
      [{ id: 'e4-a', capabilities: [] }],
      { maxAttempts: 2 },
    )
    registerAgent('e4-a')
    const result = await manager.run(
      {
        tasks: [{ id: 't1', prompt: 'S1-MARKER hello', agentId: 'e4-a', timeoutMs: 400 }],
      },
      { runId: 'e4-s1', input: 'S1' },
    )
    expect(result.status).toBe('completed')
    expect(result.attempts).toBe(2)
    expect(result.failures[0]?.code).toBe('TIMEOUT')
    expect(result.decisions).toEqual(['retry', 'completed'])
    const report = sequentialReport(result)
    expect(report.steps[0]?.status).toBe('completed')
  }, 60_000)

  it('S2: agent unavailable -> repair/reroute -> success', async () => {
    // ghost IS routable by the manager but NOT registered for real execution;
    // the runner reports it missing at runtime -> repair re-routes to live.
    const { manager, registerAgent } = await bootScenario(
      'S2-NEVER',
      'echo',
      [{ id: 'e4-ghost', capabilities: [] }, { id: 'e4-live', capabilities: [] }],
      { maxAttempts: 3 },
    )
    registerAgent('e4-live')
    const result = await manager.run(
      {
        tasks: [
          { id: 't1', prompt: 'S2 first', agentId: 'e4-ghost' },
          { id: 't2', prompt: 'S2 second', agentId: 'e4-live' },
        ],
      },
      { runId: 'e4-s2', input: 'S2' },
    )
    expect(result.status).toBe('completed')
    expect(result.repairsUsed).toBe(1)
    expect(result.failures[0]?.code).toBe('AGENT_UNAVAILABLE')
    expect(result.decisions).toEqual(['repair', 'completed'])
    const report = sequentialReport(result)
    expect(report.steps.every((step) => step.agentId === 'e4-live')).toBe(true)
    expect(report.steps.every((step) => step.status === 'completed')).toBe(true)
  }, 45_000)

  it('S3: deterministic replan -> real execution', async () => {
    const { manager, registerAgent } = await bootScenario(
      'S3-MARKER',
      'error-once',
      [{ id: 'e4-c', capabilities: [] }],
      { maxAttempts: 3, maxReplans: 2 },
    )
    registerAgent('e4-c')
    const result = await manager.run(
      {
        tasks: [
          { id: 'a', prompt: 'S3 draft', agentId: 'e4-c' },
          { id: 'b', prompt: 'S3-MARKER refine b', agentId: 'e4-c' },
          { id: 'c', prompt: 'S3 polish c', agentId: 'e4-c' },
        ],
      },
      { runId: 'e4-s3', input: 'S3' },
    )
    expect(result.status).toBe('completed')
    expect(result.replansUsed).toBe(1)
    expect(result.failures[0]?.code).toBe('DEPENDENCY_FAILURE')
    expect(result.decisions).toEqual(['replan', 'completed'])
    const report = sequentialReport(result)
    expect(report.steps.length).toBe(1)
    expect(report.steps[0]?.status).toBe('completed')
  }, 60_000)

  it('S4: cancellation -> no retry / no repair / no replan', async () => {
    const { manager, registerAgent } = await bootScenario(
      'S4-MARKER',
      'hang-once',
      [{ id: 'e4-a', capabilities: [] }],
      { maxAttempts: 5, maxReplans: 5 },
    )
    registerAgent('e4-a')
    const controller = new AbortController()
    const pending = manager.run(
      { tasks: [{ id: 't1', prompt: 'S4-MARKER hang', agentId: 'e4-a' }] },
      { runId: 'e4-s4', input: 'S4', signal: controller.signal },
    )
    await new Promise((resolve) => setTimeout(resolve, 250))
    controller.abort()
    const result = await pending
    expect(result.status).toBe('cancelled')
    expect(result.decisions).toEqual(['abort'])
    expect(result.attempts).toBe(1)
    expect(result.repairsUsed).toBe(0)
    expect(result.replansUsed).toBe(0)
  }, 30_000)
})
