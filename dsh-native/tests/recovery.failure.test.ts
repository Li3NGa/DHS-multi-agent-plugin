/**
 * Phase E4 — Failure Model & Classification (scenarios 1-2).
 */
import { describe, expect, it } from 'vitest'
import {
  SupervisorCancellationError,
  SupervisorExecutionError,
  SupervisorTimeoutError,
  SupervisorValidationError,
} from '../src/supervisor'
import { PlanRoutingError } from '../src/planner/errors'
import { classifyResult, classifyThrown, RECOVERABILITY } from '../src/recovery/failure'
import type { SupervisorRunResult } from '../src/supervisor'

function broadcastResult(entries: Record<string, unknown>[]): SupervisorRunResult {
  return {
    runId: 'r',
    status: 'failed',
    report: {
      strategy: 'broadcast',
      report: { responses: entries, joined: '', ok: false } as never,
    },
    errors: [],
    metadata: undefined,
    durationMs: 1,
  }
}

describe('Failure Model recoverability matrix (scenario 2)', () => {
  it('pins the frozen table', () => {
    expect(RECOVERABILITY.VALIDATION_ERROR).toEqual({
      retryable: false, repairable: false, replanable: false, fatal: true,
    })
    expect(RECOVERABILITY.CANCELLED.fatal).toBe(true)
    expect(RECOVERABILITY.TIMEOUT.retryable).toBe(true)
    expect(RECOVERABILITY.AGENT_UNAVAILABLE.repairable).toBe(true)
    expect(RECOVERABILITY.DEPENDENCY_FAILURE.replanable).toBe(true)
    expect(RECOVERABILITY.RUNTIME_ERROR.retryable).toBe(false)
    expect(RECOVERABILITY.TASK_ERROR.retryable).toBe(false)
  })
})

describe('Failure classification (scenario 1)', () => {
  it('classifies thrown supervisor errors', () => {
    const cancelled = classifyThrown(new SupervisorCancellationError('bye'), 1)
    expect(cancelled.code).toBe('CANCELLED')
    expect(cancelled.recoverability.fatal).toBe(true)

    const timeout = classifyThrown(new SupervisorTimeoutError('slow'), 1)
    expect(timeout.code).toBe('TIMEOUT')
    expect(timeout.recoverability.retryable).toBe(true)

    const invalid = classifyThrown(new SupervisorValidationError('bad'), 1)
    expect(invalid.code).toBe('VALIDATION_ERROR')

    const exec = classifyThrown(new SupervisorExecutionError('boom', { cause: new Error('x') }), 1)
    expect(exec.code).toBe('RUNTIME_ERROR')
    // original error is never swallowed
    expect(((exec.cause as SupervisorExecutionError).cause as Error).message).toBe('x')
  })

  it('classifies planner-layer errors', () => {
    expect(classifyThrown(new PlanRoutingError('no pool'), 1).code).toBe('ROUTING_ERROR')
  })

  it('extracts task failures with priority (agent > dep > timeout)', () => {
    const record = classifyResult(
      broadcastResult([
        { taskId: 'bc-0', agentId: 'gone', status: 'failed', error: "agent 'gone' not found" },
        { taskId: 'bc-1', agentId: 'a', status: 'cancelled', error: "dependency 'bc-0' failed" },
      ]),
      1,
    )
    expect(record.code).toBe('AGENT_UNAVAILABLE')
    expect(record.taskFailures?.map((f) => f.code)).toContain('DEPENDENCY_FAILURE')
    expect(record.taskFailures?.length).toBe(2)
  })

  it('classifies timeouts from runner markers', () => {
    const record = classifyResult(
      broadcastResult([
        { taskId: 'bc-0', agentId: 'a', status: 'failed', error: 'timeout: turn did not complete (no turn/end)' },
      ]),
      1,
    )
    expect(record.code).toBe('TIMEOUT')
    expect(record.taskId).toBe('bc-0')
  })
})
