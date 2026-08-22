/**
 * Release-entry smoke: the ROOT package's dist/index.js — the exact file
 * `dsh plugin add` mounts via the pnpm install model (prepare -> build ->
 * cordis.patch.yml) — must load as a real cordis plugin and run one task
 * against the real DSH harness.
 *
 * Run order matters: the root build (pnpm run build at the repo root)
 * must have produced dist/index.js before this spec runs
 * (root script test:smoke does exactly that).
 */
import { afterAll, beforeAll, describe, expect, it } from 'vitest'
import { SessionId } from '@deepseek-ai/dsh-session'
import type { Context } from '@deepseek-ai/cordis'
import { bootHarness, realAgent, ScriptedAdapter } from './support'
import type { MultiAgentApi } from '../../src/index'

type BundleExports = {
  apply: (ctx: Context, config?: Record<string, unknown>) => void
  inject: readonly string[]
}

// the BUILT root entry, as the DSH installer would import it
const rootEntryUrl = new URL('../../../../dist/index.js', import.meta.url).href
const rootEntry = (await import(/* @vite-ignore */ rootEntryUrl)) as BundleExports

const adapter = new ScriptedAdapter(['echo'], 'echo')
let ctx: Context

beforeAll(async () => {
  ctx = await bootHarness(adapter)
  await ctx.plugin(
    { apply: rootEntry.apply, inject: [...rootEntry.inject] } as Parameters<typeof ctx.plugin>[0],
    {},
  )
})

afterAll(async () => {
  await (ctx as unknown as { dispose?: () => Promise<void> }).dispose?.()
})

describe('root release entry (dsh plugin add path)', () => {
  it('exposes the plugin surface a host mounts', () => {
    expect(typeof rootEntry.apply).toBe('function')
    expect(rootEntry.inject).toContain('agents')
  })

  it('provides ctx.multiAgent through the real provide path', () => {
    const api = (ctx as unknown as { multiAgent: MultiAgentApi }).multiAgent
    expect(api).toBeDefined()
    expect(typeof api.scheduler).toBe('function')
  })

  it('runs a task end to end through the release entry', async () => {
    realAgent(ctx, 'root-entry-agent')
    const { TaskGraph } = await import('../../src/graph')
    const graph = new TaskGraph()
    graph.add({ id: 'only', agentId: 'root-entry-agent', prompt: 'release check', timeoutMs: 10_000 })
    const api = (ctx as unknown as { multiAgent: MultiAgentApi }).multiAgent
    const report = await api.scheduler().run(graph)
    expect(report.ok).toBe(true)
    expect(report.results.get('only')?.text).toBe('release check')
  })
})
