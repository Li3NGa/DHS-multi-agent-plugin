import { Context } from '@deepseek-ai/cordis'
import AgentRegistry, { type Agent } from '@deepseek-ai/dsh-agent'
import { createUserMessage } from '@deepseek-ai/dsh-llm'
import { Session, SessionId } from '@deepseek-ai/dsh-session'
import { describe, expect, it } from 'vitest'
import { apply, name } from '../src/index.js'

function fakeAgent(id: string, response: string): Agent {
  const session = Session.create(SessionId(id))
  const ctx = new Context()
  const agent = {
    id: SessionId(id),
    options: {},
    session,
    inbox: {} as Agent['inbox'],
    status: 'idle' as const,
    ctx,
    send: () => {},
    followup: () => {
      const message = createUserMessage({
        content: [{ type: 'text', text: 'prompt' }],
        source: { kind: 'user' },
      })
      session.append('user/message', message, { surfaceOp: 'append' })
      const assistant = createUserMessage({
        content: [{ type: 'text', text: response }],
        source: { kind: 'user' },
      })
      session.append('assistant/message', {
        message: assistant,
        surfaceOp: 'append',
        sourceEventSeqs: [],
      })
    },
    steer: () => ({ outcome: Promise.resolve({ status: 'rejected' as const }) }),
    inject: () => {},
    cancel: () => {},
    runMaintenance: <T>(task: (signal: AbortSignal) => T) => task(new AbortController().signal),
    whenIdle: () => Promise.resolve(),
  } as unknown as Agent
  return agent
}

async function harness() {
  const ctx = new Context()
  await ctx.plugin(AgentRegistry)
  await ctx.plugin({ apply, name })
  return ctx
}

describe('dhs-multi-agent native plugin', () => {
  it('loads as a Cordis plugin', async () => {
    const ctx = new Context()
    await ctx.plugin(AgentRegistry)
    const fiber = await ctx.plugin({ apply, name })

    expect(fiber).toBeDefined()
    expect(ctx.multiAgent).toBeDefined()

    await ctx.fiber.dispose()
  })

  it('registers the MultiAgent service', async () => {
    const ctx = await harness()

    expect(ctx.multiAgent.constructor.name).toBe('MultiAgentService')

    await ctx.fiber.dispose()
  })

  it('rejects a missing agent without fabricating a provider', async () => {
    const ctx = await harness()

    await expect(ctx.multiAgent.run({
      strategy: 'broadcast',
      agents: ['missing'],
      prompt: 'hello',
    })).rejects.toThrow('agent "missing" not found')

    await ctx.fiber.dispose()
  })

  it('executes one Task through ctx.agents and returns the DSH session result', async () => {
    const ctx = await harness()
    const agent = fakeAgent('agent-a', 'result-a')
    ctx.agents.register(agent)

    const result = await ctx.multiAgent.run({
      strategy: 'broadcast',
      agents: ['agent-a'],
      prompt: 'hello',
    })

    expect(result).toEqual({
      strategy: 'broadcast',
      results: [{ agent: 'agent-a', content: 'result-a' }],
    })

    await ctx.fiber.dispose()
  })

  it('broadcasts one Task to every selected DSH Agent and preserves request order', async () => {
    const ctx = await harness()
    ctx.agents.register(fakeAgent('agent-a', 'A'))
    ctx.agents.register(fakeAgent('agent-b', 'B'))

    const result = await ctx.multiAgent.run({
      strategy: 'broadcast',
      agents: ['agent-a', 'agent-b'],
      prompt: 'shared prompt',
    })

    expect(result.results).toEqual([
      { agent: 'agent-a', content: 'A' },
      { agent: 'agent-b', content: 'B' },
    ])

    await ctx.fiber.dispose()
  })
})
