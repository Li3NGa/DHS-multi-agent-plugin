import { describe, expect, it } from 'vitest'
import { AgentRouter } from '../../src/planner/router'

const agent = (id: string) => ({ id, capabilities: [] as string[] })

describe('AgentRouter agent pool invariants', () => {
  it('rejects an empty agent id', () => {
    expect(() => new AgentRouter({ agents: [agent('')] }))
      .toThrow('agent pool contains an agent with an empty id')
  })

  it('rejects duplicate agent ids', () => {
    expect(() => new AgentRouter({ agents: [agent('a'), agent('a')] }))
      .toThrow("agent pool contains duplicate agent id 'a'")
  })

  it('accepts a unique pool and preserves routing semantics', () => {
    const router = new AgentRouter({
      agents: [agent('a'), agent('b')],
    })
    const first = router.route([
      { id: 't1', prompt: 'p' },
      { id: 't2', prompt: 'p' },
    ])

    expect(first.assignments.map((item) => item.agentId)).toEqual(['a', 'b'])
    expect(first.assignments.map((item) => item.reason)).toEqual(['round-robin', 'round-robin'])
  })
})
