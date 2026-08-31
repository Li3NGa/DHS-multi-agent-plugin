/**
 * Phase E4 — Repair V1 (scenarios 6, 7, 8).
 */
import { describe, expect, it } from 'vitest'
import type { TaskExecute, Task } from '../src'
import { okOutcome } from './helpers'
import { applyIssueRepairs, clearAgentAssignments } from '../src/recovery/repair'
import { createRecoveryManager } from '../src/recovery'
import { PlanValidator } from '../src/planner/validator'
import { createSupervisor } from '../src/supervisor'

describe('applyIssueRepairs (validator repair migrated here)', () => {
  it('drops an unknown explicit agent (scenario 6)', () => {
    const plan = { tasks: [{ id: 'a', prompt: 'p', agentId: 'ghost' }] }
    const validator = new PlanValidator({ agents: [{ id: 'real', capabilities: [] }] })
    const validated = validator.validate(plan)
    const repaired = applyIssueRepairs(validated.plan, validated.issues)
    expect(repaired).toBeDefined()
    expect(repaired!.plan.tasks[0]!.agentId).toBeUndefined()
    expect(repaired!.records[0]?.action).toBe('drop-agent')
  })

  it('keeps prompts / ids / dependencies untouched', () => {
    const plan = {
      tasks: [
        { id: 'a', prompt: 'keep-me', agentId: 'ghost', dependsOn: [], metadata: { n: 1 } },
      ],
    }
    const validator = new PlanValidator({ agents: [{ id: 'real', capabilities: [] }] })
    const validated = validator.validate(plan)
    const repaired = applyIssueRepairs(validated.plan, validated.issues)!
    expect(repaired.plan.tasks[0]).toMatchObject({
      id: 'a', prompt: 'keep-me', dependsOn: [], metadata: { n: 1 },
    })
  })

  it('returns undefined when nothing is repairable', () => {
    const plan = { tasks: [{ id: 'a', prompt: 'p' }] }
    const validator = new PlanValidator({ agents: [{ id: 'real', capabilities: [] }] })
    const validated = validator.validate(plan)
    expect(applyIssueRepairs(validated.plan, validated.issues)).toBeUndefined()
  })
})

describe('clearAgentAssignments', () => {
  it('clears only the failed explicit assignments', () => {
    const plan = {
      tasks: [
        { id: 't1', prompt: 'p', agentId: 'gone' },
        { id: 't2', prompt: 'q', agentId: 'stay' },
      ],
    }
    const result = clearAgentAssignments(plan, ['t1'])
    expect(result.ok).toBe(true)
    if (result.ok) {
      expect(result.plan.tasks[0]!.agentId).toBeUndefined()
      expect(result.plan.tasks[1]!.agentId).toBe('stay')
    }
  })

  it('rejects with nothing-to-repair when no explicit assignment exists', () => {
    const plan = { tasks: [{ id: 't1', prompt: 'p' }] }
    const result = clearAgentAssignments(plan, ['t1'])
    expect(result.ok).toBe(false)
    if (!result.ok) expect(result.code).toBe('nothing-to-repair')
  })
})

describe('Manager-level routing repair', () => {
  it('scenario 7: unavailable agent -> repair -> re-route -> success', async () => {
    let calls = 0
    const execute: TaskExecute = async (task: Task) => {
      calls += 1
      if (task.agentId === 'x') {
        return {
          taskId: task.id,
          status: 'failed' as const,
          text: undefined,
          error: `agent '${task.agentId}' not found`,
          durationMs: 1,
          raw: undefined,
        }
      }
      return okOutcome(task.id)
    }
    const manager = createRecoveryManager({
      supervisor: createSupervisor({ execute }),
      agents: [{ id: 'x', capabilities: [] }, { id: 'y', capabilities: [] }],
      policy: { maxAttempts: 3 },
    })
    const result = await manager.run(
      { tasks: [
        { id: 's1', prompt: 'first', agentId: 'x' },
        { id: 's2', prompt: 'second', agentId: 'y' },
      ] },
      { runId: 'r7', input: 'p' },
    )
    expect(result.status).toBe('completed')
    expect(result.repairsUsed).toBe(1)
    expect(result.decisions).toEqual(['repair', 'completed'])
    // both steps now run on the live agent
    if (result.lastResult?.report.strategy === 'sequential') {
      expect(result.lastResult.report.report.steps.map((s) => s.agentId)).toEqual(['y', 'y'])
    } else {
      expect.unreachable('expected sequential report')
    }
    void calls
  })

  it('scenario 8: repair rejection -> failed without pretending progress', async () => {
    const execute: TaskExecute = async (task: Task) => ({
      taskId: task.id,
      status: 'failed' as const,
      text: undefined,
      error: "agent 'whoever' not found",
      durationMs: 1,
      raw: undefined,
    })
    const manager = createRecoveryManager({
      supervisor: createSupervisor({ execute }),
      agents: [{ id: 'real', capabilities: [] }],
      policy: { maxAttempts: 3 },
    })
    // task has NO explicit assignment: Router already picked the best agent,
    // so there is nothing for the Repair layer to clear.
    const result = await manager.run(
      { tasks: [{ id: 't1', prompt: 'p' }] },
      { runId: 'r8', input: 'p' },
    )
    expect(result.status).toBe('failed')
    expect(result.repairsUsed).toBe(0)
    expect(result.failures[0]?.code).toBe('AGENT_UNAVAILABLE')
  })
})
