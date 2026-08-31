/**
 * Public recovery entrypoint verification against the built Native bundle and
 * the real DSH harness. The first attempt intentionally references an
 * unavailable explicit agent; RecoveryManager must repair the plan, evict the
 * dead agent from the run-local pool, reroute to the declared live agent, and
 * then execute successfully through the real runtime.
 */
import { beforeAll, describe, expect, it, afterAll } from 'vitest'
import type { Context } from '@deepseek-ai/cordis'
import { bootHarness, ScriptedAdapter, type ConfigAgentEntry } from './support'
import type { MultiAgentApi } from '../../src/index'

type BundleApi = { MultiAgentApi: never }
const bundleUrl = new URL('../../dist/dsh.bundle.js', import.meta.url).href
const bundle = (await import(/* @vite-ignore */ bundleUrl)) as typeof import('../../src/index') & BundleApi
const adapter = new ScriptedAdapter(['echo'])
const contexts: Context[] = []

function apiOf(ctx: Context): MultiAgentApi {
  return (ctx as unknown as { multiAgent: MultiAgentApi }).multiAgent
}

describe('public recovery entrypoint on real DSH', () => {
  let ctx: Context

  beforeAll(async () => {
    ctx = await bootHarness(adapter, [
      { id: 'live', sessionId: 'live', provider: 'mock', model: 'mock' } satisfies ConfigAgentEntry,
    ])
    contexts.push(ctx)
    await ctx.plugin(
      { apply: bundle.apply, inject: [...bundle.inject] } as Parameters<Context['plugin']>[0],
      {},
    )
  })

  afterAll(async () => {
    await Promise.all(contexts.map((item) =>
      (item as unknown as { dispose?: () => Promise<void> }).dispose?.(),
    ))
  })

  it('repairs an unavailable agent and reroutes to a live config-created agent', async () => {
    const result = await apiOf(ctx).runWithRecovery(
      { tasks: [{ id: 'task-a', agentId: 'dead', prompt: 'recover me' }] },
      {
        runId: 'r4-smoke',
        input: 'recover me',
        agents: [
          { id: 'dead', capabilities: [] },
          { id: 'live', capabilities: [] },
        ],
        recovery: { maxAttempts: 3 },
      },
    )

    expect(result.status).toBe('completed')
    expect(result.attempts).toBe(2)
    expect(result.repairsUsed).toBe(1)
    expect(result.decisions).toEqual(['repair', 'completed'])
    expect(result.lastResult?.status).toBe('completed')
  })
})
