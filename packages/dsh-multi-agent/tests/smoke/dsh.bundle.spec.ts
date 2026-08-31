/**
 * Full-bundle release verification against the REAL DSH runtime.
 *
 * Scope distinction (do not conflate):
 * - REAL DSH RUNTIME ✔ — the actual @deepseek-ai/cordis Context plus the
 *   real dsh-llm / dsh-session / dsh-system-prompt / dsh-tools / dsh-agent
 *   / dsh-agent-loop services from npm, loading the BUILT artifact
 *   dist/dsh.bundle.js (not the TypeScript sources). External
 *   `@deepseek-ai/*` imports must resolve through the real node_modules,
 *   exactly as a host would provide them.
 * - FULL DESKTOP/TUI ENVIRONMENT ✘ — the desktop `dsh` application and its
 *   cordis.patch.yml / $bundle plugin loader are not present on this
 *   machine (no ~/.dsh). That final wiring step ships as
 *   cordis.patch.yml.example and stays PARTIALLY VERIFIED until run in a
 *   desktop install.
 *
 * Covers: bundle load, external resolution, service provision via
 * ctx.reflect.provide, plugin lifecycle (unload leaves no residue,
 * reload works), and config-created (declarative) agents end to end:
 * DSH config -> agent_loop.create -> ctx.agents -> AgentRunner -> Task.
 */
import { afterAll, beforeAll, describe, expect, it } from 'vitest'
import { SessionId } from '@deepseek-ai/dsh-session'
import type { Context } from '@deepseek-ai/cordis'
import { bootHarness, ScriptedAdapter, type ConfigAgentEntry } from './support'
import type { MultiAgentApi } from '../../src/index'

type BundleExports = {
  apply: (ctx: Context, config?: Record<string, unknown>) => void
  inject: readonly string[]
}

// the BUILT artifact, as a host would import it; the runtime URL keeps TS
// from trying to typecheck the generated bundle
const bundleUrl = new URL('../../dist/dsh.bundle.js', import.meta.url).href
const bundle = (await import(/* @vite-ignore */ bundleUrl)) as BundleExports

const adapter = new ScriptedAdapter(['echo'], 'echo')

function multiAgentOf(ctx: Context): MultiAgentApi | undefined {
  return (ctx as unknown as { multiAgent?: MultiAgentApi }).multiAgent
}

afterAll(async () => {
  await Promise.all(contexts.map((ctx) =>
    (ctx as unknown as { dispose?: () => Promise<void> }).dispose?.(),
  ))
})

const contexts: Context[] = []

describe('full bundle on the real DSH runtime', () => {
  let ctx: Context
  let mounted: Awaited<ReturnType<Context['plugin']>> | undefined

  beforeAll(async () => {
    ctx = await bootHarness(adapter)
    contexts.push(ctx)
  })

  it('loads dist/dsh.bundle.js and provides ctx.multiAgent via the real provide path', async () => {
    expect(typeof bundle.apply).toBe('function')
    expect(bundle.inject).toContain('agents')
    mounted = await ctx.plugin(
      { apply: bundle.apply, inject: [...bundle.inject] } as Parameters<typeof ctx.plugin>[0],
      {},
    )
    const api = multiAgentOf(ctx)
    expect(api).toBeDefined()
  })

  it('runs a single task through the bundle-mounted API', async () => {
    // agent created programmatically here; config-created agents below
    ctx.agentLoop.create(SessionId('b1'), { provider: 'mock', model: 'mock' })
    const { TaskGraph } = await import('../../src/graph')
    const graph = new TaskGraph()
    graph.add({ id: 't', agentId: 'b1', prompt: 'bundle check', timeoutMs: 10_000 })
    const report = await multiAgentOf(ctx)!.scheduler().run(graph)
    expect(report.ok).toBe(true)
    expect(report.results.get('t')?.text).toBe('bundle check')
  })

  it('runs an arbitrary DAG through the bundle-mounted API without linearization', async () => {
    const api = multiAgentOf(ctx)!
    const report = await api.runDag([
      { id: 'a', agentId: 'b1', prompt: 'dag-a' },
      { id: 'b', agentId: 'b1', prompt: 'dag-b' },
      { id: 'c', agentId: 'b1', prompt: 'dag-c', dependsOn: ['a', 'b'] },
    ], { concurrency: 2 })
    expect(report.ok).toBe(true)
    expect([...report.results.keys()]).toEqual(['a', 'b', 'c'])
    expect(report.results.get('a')?.text).toBe('dag-a')
    expect(report.results.get('b')?.text).toBe('dag-b')
    expect(report.results.get('c')?.text).toBe('dag-c')
  })

  it('unloading the plugin fiber removes the service (no residue) and reload works', async () => {
    // dispose the fiber mounted by the first test
    await mounted!.dispose()
    expect(multiAgentOf(ctx)).toBeUndefined()

    const second = await ctx.plugin(
      { apply: bundle.apply, inject: [...bundle.inject] } as Parameters<typeof ctx.plugin>[0],
      {},
    )
    expect(multiAgentOf(ctx)).toBeDefined()
    await second.dispose()
    expect(multiAgentOf(ctx)).toBeUndefined()
  })
})

describe('config-created agents (DSH config -> agent_loop.create -> ctx.agents -> tasks)', () => {
  // declarative agents: the AgentLoop service itself creates them at boot
  // from its config — no test-side create() calls
  const configAgents: readonly ConfigAgentEntry[] = [
    { id: 'cw1', sessionId: 'cw1', provider: 'mock', model: 'mock' },
    { id: 'cw2', sessionId: 'cw2', provider: 'mock', model: 'mock' },
  ]
  let ctx: Context
  let multiAgent: MultiAgentApi

  beforeAll(async () => {
    ctx = await bootHarness(adapter, configAgents)
    contexts.push(ctx)
    await ctx.plugin(
      { apply: bundle.apply, inject: [...bundle.inject] } as Parameters<typeof ctx.plugin>[0],
      {},
    )
    multiAgent = multiAgentOf(ctx)!
  })

  it('creates the declared agents at boot (registry lookup, no manual create)', () => {
    expect(ctx.agents.get(SessionId('cw1'))).toBeDefined()
    expect(ctx.agents.get(SessionId('cw2'))).toBeDefined()
    expect(ctx.agents.get(SessionId('cw1'))!.id).toBe(SessionId('cw1'))
  })

  it('runs a single task on a config-created agent', async () => {
    const { TaskGraph } = await import('../../src/graph')
    const graph = new TaskGraph()
    graph.add({ id: 'only', agentId: 'cw1', prompt: 'config agent task', timeoutMs: 10_000 })
    const report = await multiAgent.scheduler().run(graph)
    expect(report.ok).toBe(true)
    expect(report.results.get('only')?.text).toBe('config agent task')
  })

  it('broadcasts to two config-created agents in parallel', async () => {
    const report = await multiAgent.runBroadcast({
      prompt: 'config broadcast',
      agents: [{ agentId: 'cw1' }, { agentId: 'cw2' }],
    })
    expect(report.ok).toBe(true)
    expect(report.responses.map((entry) => entry.agentId)).toEqual(['cw1', 'cw2'])
    expect(report.responses.every((entry) => entry.text === 'config broadcast')).toBe(true)
  })

  it('sequential: config agents pass results between each other', async () => {
    const report = await multiAgent.runSequential([
      { agentId: 'cw1', prompt: 'first step' },
      { agentId: 'cw2', prompt: (previous) => `next after: ${previous?.text}` },
    ])
    expect(report.ok).toBe(true)
    expect(report.steps[0]!.text).toBe('first step')
    expect(report.steps[1]!.text).toBe('next after: first step')
  })

  it('relay: config agents thread the draft', async () => {
    const report = await multiAgent.runRelay({
      prompt: 'relay via config agents',
      steps: [{ agentId: 'cw1' }, { agentId: 'cw2' }],
    })
    expect(report.ok).toBe(true)
    expect(report.turns[1]!.output).toContain(report.turns[0]!.output!)
    expect(report.draft).toBe(report.turns[1]!.output)
  })
})
