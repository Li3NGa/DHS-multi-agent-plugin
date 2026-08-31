import { describe, expect, it } from 'vitest'
import type { PlannerV1, TaskExecute } from '../../src'
import { planAndRunDag } from '../../src/planner'

const planner = {
  plan: async () => ({
    plan: { tasks: [{ id: 'a', prompt: 'p' }] },
    format: 'json' as const,
  }),
} as PlannerV1

const execute: TaskExecute = async () => {
  throw new Error('execute should not be called for invalid timeout')
}

const agents = [{ id: 'a', capabilities: [] }]

describe('run-level timeout validation', () => {
  it.each([0, -1, Number.NaN, Number.POSITIVE_INFINITY])(
    'rejects invalid DAG timeout %s before planning/execution',
    async (timeoutMs) => {
      let plannerCalls = 0
      const guardedPlanner = {
        plan: async () => {
          plannerCalls += 1
          return planner.plan('p')
        },
      } as PlannerV1

      await expect(
        planAndRunDag('p', execute, { planner: guardedPlanner, agents }, {
          runId: 'invalid-timeout',
          timeoutMs,
        }),
      ).rejects.toThrow('timeoutMs must be a finite number > 0')
      expect(plannerCalls).toBe(0)
    },
  )
})
