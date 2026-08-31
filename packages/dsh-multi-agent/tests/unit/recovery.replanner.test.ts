/**
 * Phase E4 — Replan V1 (scenarios 9-12).
 */
import { describe, expect, it } from 'vitest'
import type { TaskExecute, Task } from '../src'
import { okOutcome } from './helpers'
import { deterministicReplan } from '../src/recovery/replanner'
import { createRecoveryManager, RetryPolicy } from '../src/recovery'
import { AgentRouter } from '../src/planner/router'
import { PlanValidator } from '../src/planner/validator'
import { createSupervisor } from '../src/supervisor'
import type { FailureRecord } from '../src/recovery'

const AGENTS = [{ id: 'x', capabilities: [] }, { id: 'y', capabilities: [] }]

function depFailure(taskFailures: { taskId: string; code: string; message: string }[]): FailureRecord {
  return {
    code: 'DEPENDENCY_FAILURE',
    message: 'cascade',
    attempt: 1,
    recoverability: { retryable: false, repairable: false, replanable: true, fatal: false },
    timestamp: new Date().toISOString(),
    taskFailures: taskFailures.map((t) => ({
      taskId: t.taskId,
      agentId: undefined,
      code: t.code as never,
      message: t.message,
    })),
  }
}

describe('deterministicReplan (scenario 9)', () => {
  it('prunes the failed subtree transitively and deterministically', () => {
    const plan = {
      tasks: [
        { id: 'a', prompt: 'pa' },
        { id: 'b', prompt: 'pb', dependsOn: ['a'] },
        { id: 'c', prompt: 'pc', dependsOn: ['b'] },
        { id: 'z', prompt: 'pz' },
      ],
    }
    const failure = depFailure([
      { taskId: 'b', code: 'TASK_ERROR', message: 'boom' },
      { taskId: 'c', code: 'DEPENDENCY_FAILURE', message: "dependency 'b' failed" },
    ])
    const result = deterministicReplan({ plan, failure })
    expect(result.ok).toBe(true)
    if (result.ok) {
      expect(result.rule).toBe('prune-failed-subtree')
      expect([...result.removedTaskIds].sort()).toEqual(['b', 'c'])
      expect(result.plan.tasks.map((t) => t.id)).toEqual(['a', 'z'])
    }
  })

  it('rejects unsupported codes', () => {
    const plan = { tasks: [{ id: 'a', prompt: 'p' }] }
    const base = depFailure([{ taskId: 'a', code: 'TASK_ERROR', message: 'm' }])
    const wrongCode = deterministicReplan({ plan, failure: { ...base, code: 'TIMEOUT' as never } })
    expect(wrongCode.ok).toBe(false)
    if (!wrongCode.ok) expect(wrongCode.code).toBe('unsupported-failure-code')
  })

  it('rejects an emptied plan instead of executing nothing', () => {
    const plan = { tasks: [{ id: 'a', prompt: 'p' }] }
    const all = depFailure([{ taskId: 'a', code: 'TASK_ERROR', message: 'm' }])
    const emptied = deterministicReplan({ plan, failure: all })
    expect(emptied.ok).toBe(false)
    if (!emptied.ok) expect(emptied.code).toBe('empty-plan')
  })
})

describe('replan pipeline guarantees (scenarios 10, 11)', () => {
  it('scenario 10: replanned candidate passes validation', () => {
    const plan = {
      tasks: [
        { id: 'a', prompt: 'pa' },
        { id: 'b', prompt: 'pb', dependsOn: ['a'] },
        { id: 'c', prompt: 'pc', dependsOn: ['b'] },
        { id: 'd', prompt: 'pd' },
      ],
    }
    const failure = depFailure([
      { taskId: 'b', code: 'TASK_ERROR', message: 'boom' },
      { taskId: 'c', code: 'DEPENDENCY_FAILURE', message: 'dep' },
    ])
    const result = deterministicReplan({ plan, failure })
    expect(result.ok).toBe(true)
    if (!result.ok) return
    const validated = new PlanValidator({ agents: AGENTS }).validate(result.plan)
    expect(validated.issues.filter((i) => i.severity === 'error')).toHaveLength(0)
  })

  it('scenario 11: replanned candidate is routable end-to-end', () => {
    const plan = {
      tasks: [
        { id: 'a', prompt: 'pa' },
        { id: 'b', prompt: 'pb', dependsOn: ['a'] },
      ],
    }
    const failure = depFailure([
      { taskId: 'b', code: 'DEPENDENCY_FAILURE', message: "dependency 'a' failed" },
    ])
    const result = deterministicReplan({ plan, failure })
    expect(result.ok).toBe(true)
    if (!result.ok) return
    const routed = new AgentRouter({ agents: AGENTS }).route(result.plan.tasks)
    expect(routed.assignments.length).toBe(result.plan.tasks.length)
    expect(routed.assignments.every((a) => AGENTS.some((g) => g.id === a.agentId))).toBe(true)
  })
})

describe('scenario 12: replans are bounded', () => {
  it('policy boundary is deterministic', () => {
    const policy = new RetryPolicy({ maxReplans: 1 })
    expect(policy.canReplan(0)).toBe(true)
    expect(policy.canReplan(1)).toBe(false)
  })

  it('maxReplans=0 blocks replan entirely (straight failed)', async () => {
    let calls = 0
    const execute: TaskExecute = async (task: Task) => {
      calls += 1
      void task
      if (calls === 1) {
        return {
          taskId: task.id,
          status: 'failed' as const,
          text: undefined,
          error: 'turn ended: error',
          durationMs: 1,
          raw: undefined,
        }
      }
      return okOutcome(task.id)
    }
    const manager = createRecoveryManager({
      supervisor: createSupervisor({ execute }),
      agents: AGENTS,
      policy: { maxAttempts: 3, maxReplans: 0 },
    })
    // a fails, b dep-cancelled -> DEPENDENCY_FAILURE, but no replan budget.
    const result = await manager.run(
      { tasks: [{ id: 'a', prompt: 'pa' }, { id: 'b', prompt: 'pb', dependsOn: ['a'] }] },
      { runId: 'r12', input: 'p' },
    )
    expect(result.status).toBe('failed')
    expect(result.failures[0]?.code).toBe('DEPENDENCY_FAILURE')
    expect(result.decisions).toEqual(['failed'])
    expect(result.replansUsed).toBe(0)
  })
})
