/**
 * Real-harness smoke verification (DSH -> Cordis -> dsh-multi-agent ->
 * ctx.multiAgent -> Task -> AgentRunner -> real DSH Agent -> real Session
 * -> real session events). The only scripted piece is the model endpoint
 * (real `ctx.llm.registerAdapter` route), which is how DSH's own upstream
 * tests drive the loop without network access.
 *
 * Cases: A plugin loads, B ctx.multiAgent registers, C ctx.agents resolves,
 * D single task, E broadcast, F sequential, G relay, H timeout, I
 * cancellation, plus Task1/Task2 result isolation on one shared agent.
 */
import { afterAll, beforeAll, describe, expect, it } from 'vitest'
import { SessionId } from '@deepseek-ai/dsh-session'
import { apply, type MultiAgentApi } from '../src/index'
import { TaskGraph } from '../src/graph'
import { bootHarness, realAgent, ScriptedAdapter } from './support'

const adapter = new ScriptedAdapter(['echo'], 'echo')
let ctx: Awaited<ReturnType<typeof bootHarness>>
let multiAgent: MultiAgentApi

beforeAll(async () => {
  ctx = await bootHarness(adapter)
  // A: the plugin loads as a cordis plugin with inject: ['agents']
  await ctx.plugin({ apply, inject: ['agents'] } as Parameters<typeof ctx.plugin>[0], {})
  // B: the API registered on the context
  multiAgent = (ctx as unknown as { multiAgent: MultiAgentApi }).multiAgent
})

afterAll(async () => {
  await (ctx as unknown as { dispose?: () => Promise<void> }).dispose?.()
})

describe('real DSH harness smoke', () => {
  it('A/B: plugin loads and ctx.multiAgent registers', () => {
    expect(multiAgent).toBeDefined()
    expect(typeof multiAgent.scheduler).toBe('function')
    expect(typeof multiAgent.runSequential).toBe('function')
    expect(typeof multiAgent.runRelay).toBe('function')
    expect(typeof multiAgent.runBroadcast).toBe('function')
  })

  it('C: ctx.agents resolves the configured real agents', () => {
    const w1 = realAgent(ctx, 'w1')
    const w2 = realAgent(ctx, 'w2')
    expect(ctx.agents.get(w1.id)).toBe(w1)
    expect(ctx.agents.get(w2.id)).toBe(w2)
    expect(ctx.agents.get(SessionId('missing'))).toBeUndefined()
  })

  it('D: single task completes through a real session', async () => {
    const agent = realAgent(ctx, 'd1')
    const graph = new TaskGraph()
    graph.add({ id: 'only', agentId: 'd1', prompt: 'what is the answer', timeoutMs: 10_000 })
    const report = await multiAgent.scheduler().run(graph)
    expect(report.ok).toBe(true)
    expect(report.results.get('only')?.status).toBe('completed')
    // echo adapter: the reply is the task prompt itself
    expect(report.results.get('only')?.text).toBe('what is the answer')
    expect(report.results.get('only')?.raw?.turnEndReason).toBe('completed')
    // the turn really lives in the real session log
    const types = agent.session.events.map((event) => event.type)
    expect(types).toContain('turn/start')
    expect(types).toContain('user/message')
    expect(types).toContain('assistant/message')
    expect(types).toContain('turn/end')
  })

  it('E: broadcast asks two real agents in parallel', async () => {
    realAgent(ctx, 'e1')
    realAgent(ctx, 'e2')
    const report = await multiAgent.runBroadcast({
      prompt: 'broadcast question',
      agents: [{ agentId: 'e1' }, { agentId: 'e2' }],
    })
    expect(report.ok).toBe(true)
    expect(report.responses.map((entry) => entry.agentId)).toEqual(['e1', 'e2'])
    expect(report.responses.every((entry) => entry.text === 'broadcast question')).toBe(true)
  })

  it('F: sequential passes the previous result into the next prompt', async () => {
    realAgent(ctx, 'f1')
    realAgent(ctx, 'f2')
    const report = await multiAgent.runSequential([
      { agentId: 'f1', prompt: 'step one' },
      { agentId: 'f2', prompt: (previous) => `given: ${previous?.text}` },
    ])
    expect(report.ok).toBe(true)
    // step 1 echoes its prompt; step 2 sees that as its previous result
    expect(report.steps[0]!.text).toBe('step one')
    expect(report.steps[1]!.text).toBe('given: step one')
  })

  it('G: relay threads the draft through real turns', async () => {
    realAgent(ctx, 'g1')
    realAgent(ctx, 'g2')
    const report = await multiAgent.runRelay({
      prompt: 'write a haiku',
      steps: [{ agentId: 'g1' }, { agentId: 'g2' }],
    })
    expect(report.ok).toBe(true)
    // turn 1 echoed the wrapped draft (prompt == initial draft);
    // turn 2's answer contains turn 1's answer as its draft
    expect(report.turns[0]!.output).toContain('write a haiku')
    expect(report.turns[1]!.output).toContain(report.turns[0]!.output!)
    expect(report.draft).toBe(report.turns[1]!.output)
  })

  it('H: task timeout cancels the real turn and never hangs the run', async () => {
    ctx.llm.registerAdapter(['mock-hang'], new ScriptedAdapter(['hang'], 'hang'))
    const agent = realAgent(ctx, 'h1-hang', 'mock-hang')
    const graph = new TaskGraph()
    graph.add({ id: 'stuck', agentId: 'h1-hang', prompt: 'never finishes', timeoutMs: 200 })
    const startedAt = Date.now()
    const report = await multiAgent.scheduler().run(graph)
    expect(Date.now() - startedAt).toBeLessThan(8_000)
    const outcome = report.results.get('stuck')
    expect(outcome?.status).toBe('failed')
    expect(outcome?.error).toContain('timeout')
    // the real turn was aborted through the host cancel path
    const end = agent.session.events.find((event) => event.type === 'turn/end')
    expect((end?.data as { reason?: { kind?: string } } | undefined)?.reason?.kind).toBe('aborted')
  })

  it('I: AbortSignal cancels the run against a hanging turn', async () => {
    ctx.llm.registerAdapter(['mock-hang2'], new ScriptedAdapter(['hang'], 'hang'))
    const agent = realAgent(ctx, 'i1-hang', 'mock-hang2')
    const graph = new TaskGraph()
    graph.add({ id: 'c1', agentId: 'i1-hang', prompt: 'cancel me', timeoutMs: 60_000 })
    const controller = new AbortController()
    const runPromise = multiAgent.scheduler().run(graph, controller.signal)
    queueMicrotask(() => controller.abort())
    const report = await runPromise
    expect(report.stopped).toBe(true)
    expect(report.results.get('c1')?.status).toBe('cancelled')
    const end = agent.session.events.find((event) => event.type === 'turn/end')
    expect((end?.data as { reason?: { kind?: string } } | undefined)?.reason?.kind).toBe('aborted')
  })

  it('isolation: task 2 never reads task 1 events on the same agent', async () => {
    const agent = realAgent(ctx, 'iso1')
    const eventsAfterNothing = agent.session.events.length
    expect(eventsAfterNothing).toBe(0)
    // two tasks on ONE agent, forced back-to-back by a dependency edge
    const graph = new TaskGraph()
    graph.add({ id: 'iso-a', agentId: 'iso1', prompt: 'FIRST SECRET', timeoutMs: 10_000 })
    graph.add({ id: 'iso-b', agentId: 'iso1', prompt: 'SECOND', dependsOn: ['iso-a'], timeoutMs: 10_000 })
    const report = await multiAgent.scheduler().run(graph)
    expect(report.ok).toBe(true)
    // both turns live in the same real session log...
    expect(agent.session.events.length).toBeGreaterThan(0)
    // ...but each task's outcome derives only from its own turn's slice:
    // if task 2's boundary leaked task 1's turn, its echo text would carry
    // FIRST SECRET; exact equality proves the correlation boundary holds
    expect(report.results.get('iso-a')?.text).toBe('FIRST SECRET')
    expect(report.results.get('iso-b')?.text).toBe('SECOND')
  })
})
