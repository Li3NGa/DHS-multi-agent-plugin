import { describe, expect, it } from 'vitest'
import { validateSupervisorInput } from '../../src/supervisor'

describe('Supervisor empty plan validation', () => {
  it('rejects an empty sequential plan', () => {
    expect(() => validateSupervisorInput({
      runId: 'r25-seq-empty',
      input: 'hello',
      plan: { strategy: 'sequential', steps: [], options: {} },
    })).toThrow('sequential steps must contain at least one step')
  })

  it('rejects an empty relay plan', () => {
    expect(() => validateSupervisorInput({
      runId: 'r25-relay-empty',
      input: 'hello',
      plan: { strategy: 'relay', options: { prompt: 'hello', steps: [] } },
    })).toThrow('relay steps must contain at least one step')
  })

  it('rejects an empty broadcast plan', () => {
    expect(() => validateSupervisorInput({
      runId: 'r25-broadcast-empty',
      input: 'hello',
      plan: { strategy: 'broadcast', options: { prompt: 'hello', agents: [] } },
    })).toThrow('broadcast agents must contain at least one agent')
  })
})
