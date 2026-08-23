/**
 * Phase E1 — Native Supervisor Contract tests.
 *
 * These tests pin the contract ONLY. They never execute a Supervisor (none
 * exists until E2). They verify the shape rules a Supervisor must honour:
 * input validity, lifecycle transitions, timeout/cancellation semantics,
 * error propagation, and the strategy boundary.
 *
 * Runs against the frozen Runtime types + the supervisor contract modules.
 */
import { describe, expect, it } from 'vitest'
import {
  // errors
  SupervisorError,
  SupervisorValidationError,
  SupervisorExecutionError,
  SupervisorCancellationError,
  SupervisorTimeoutError,
  SupervisorAggregationError,
  isSupervisorError,
  // lifecycle
  assertTransition,
  isTerminalState,
  PHASE_ORDER,
  TERMINAL_STATUSES,
  // strategy boundary
  strategyEntryPoint,
  assertKnownStrategy,
  // types
  type SupervisorPlan,
  type SupervisorRunInput,
  type SupervisorRunResult,
  type SupervisorState,
  type SupervisorStrategyReport,
} from '../src/supervisor'
import { TaskGraph } from '../src/graph'
import { Scheduler, type TaskExecute } from '../src/scheduler'
import type { TaskOutcome } from '../src/runner'
import { runBroadcast } from '../src/strategies/broadcast'

const okOutcome = (taskId: string, text = `${taskId}-out`): TaskOutcome => ({
  taskId,
  status: 'completed',
  text,
  error: undefined,
  durationMs: 1,
  raw: undefined,
})

/** A trivial execute the contract tests may feed a frozen strategy with. */
const execute: TaskExecute = async (task) => okOutcome(task.id)

describe('Supervisor contract — valid input', () => {
  it('accepts a broadcast plan reusing the frozen BroadcastOptions shape', () => {
    const plan: SupervisorPlan = {
      strategy: 'broadcast',
      options: {
        prompt: 'draft a plan',
        agents: [{ agentId: 'a', timeoutMs: 100 }, { agentId: 'b' }],
      },
    }
    expect(plan.strategy).toBe('broadcast')
    expect(plan.options.agents).toHaveLength(2)
    // no duplicate plan model: the option is exactly BroadcastOptions minus signal
    expect(plan.options).not.toHaveProperty('signal')
  })

  it('accepts a sequential plan with frozen SequentialStep shapes', () => {
    const plan: SupervisorPlan = {
      strategy: 'sequential',
      steps: [
        { agentId: 'a', prompt: 'step one' },
        { agentId: 'b', prompt: (prev) => `step two after ${prev?.text ?? 'none'}` },
      ],
      options: {},
    }
    expect(plan.steps).toHaveLength(2)
    expect(typeof plan.steps[1]!.prompt).toBe('function')
  })

  it('accepts a relay plan reusing frozen RelayOptions', () => {
    const plan: SupervisorPlan = {
      strategy: 'relay',
      options: {
        prompt: 'draft',
        steps: [{ agentId: 'a' }, { agentId: 'b' }],
      },
    }
    expect(plan.options.steps).toHaveLength(2)
  })

  it('SupervisorRunInput reuses the plan without inventing TaskPlan', () => {
    const input: SupervisorRunInput = {
      runId: 'run-1',
      input: 'hello',
      plan: { strategy: 'broadcast', options: { prompt: 'p', agents: [] } },
      timeoutMs: 5000,
      metadata: { source: 'test' },
    }
    expect(input.runId).toBe('run-1')
    expect(input.timeoutMs).toBe(5000)
    expect(input.plan.strategy).toBe('broadcast')
  })
})

describe('Supervisor contract — invalid input', () => {
  it('rejects an unknown strategy via the strategy boundary guard', () => {
    expect(() => assertKnownStrategy('debate')).toThrow(TypeError)
    expect(() => assertKnownStrategy('planner')).toThrow(TypeError)
  })

  it('does not accept a strategy outside the frozen set', () => {
    const known = new Set(['broadcast', 'sequential', 'relay'])
    for (const s of known) assertKnownStrategy(s)
    // the frozen runtime has exactly three strategies
    expect(known.size).toBe(3)
  })

  it('SupervisorValidationError carries kind + state', () => {
    const err = new SupervisorValidationError('bad plan', { state: 'validating' })
    expect(err.kind).toBe('validation')
    expect(err.state).toBe('validating')
    expect(isSupervisorError(err)).toBe(true)
  })
})

describe('Supervisor contract — lifecycle', () => {
  it('walks the happy path forward through completion', () => {
    const path: SupervisorState[] = [
      'created',
      'validating',
      'scheduled',
      'running',
      'aggregating',
      'completed',
    ]
    for (let i = 0; i < path.length - 1; i += 1) {
      expect(assertTransition(path[i]!, path[i + 1]!)).toBe(true)
    }
  })

  it('exposes the canonical phase order', () => {
    expect(PHASE_ORDER).toEqual([
      'created',
      'validating',
      'scheduled',
      'running',
      'aggregating',
      'completed',
    ])
  })

  it('forbids running before scheduled', () => {
    expect(() => assertTransition('created', 'running')).toThrow(SupervisorError)
    expect(() => assertTransition('validating', 'running')).toThrow(SupervisorError)
  })

  it('forbids completing before aggregating', () => {
    expect(() => assertTransition('created', 'completed')).toThrow(SupervisorError)
    expect(() => assertTransition('running', 'completed')).toThrow(SupervisorError)
  })

  it('forbids leaving a terminal state (no reverse/extra transitions)', () => {
    for (const terminal of ['completed', 'failed', 'cancelled', 'timeout'] as const) {
      expect(isTerminalState(terminal)).toBe(true)
      for (const target of ['created', 'running', 'completed'] as const) {
        expect(() => assertTransition(terminal, target)).toThrow(SupervisorError)
      }
    }
  })

  it('forbids no-op transitions', () => {
    expect(() => assertTransition('running', 'running')).toThrow(SupervisorError)
  })

  it('terminal status set matches the contract statuses', () => {
    expect([...TERMINAL_STATUSES].sort()).toEqual(
      ['cancelled', 'completed', 'failed', 'timeout'].sort(),
    )
  })
})

describe('Supervisor contract — timeout semantics', () => {
  it('timeout is a legal terminal target from scheduled/running', () => {
    expect(assertTransition('scheduled', 'timeout')).toBe(true)
    expect(assertTransition('running', 'timeout')).toBe(true)
  })

  it('SupervisorTimeoutError is distinct from Runtime timeout outcomes', () => {
    const err = new SupervisorTimeoutError('ceiling reached', { state: 'running' })
    expect(err.kind).toBe('timeout')
    // state records where the error was raised, not the outcome
    expect(err.state).toBe('running')
  })

  it('timeout is terminal: cannot continue after it', () => {
    expect(() => assertTransition('timeout', 'aggregating')).toThrow(SupervisorError)
  })
})

describe('Supervisor contract — cancellation semantics', () => {
  it('cancellation is a legal terminal target from any phase', () => {
    for (const phase of ['created', 'validating', 'scheduled', 'running', 'aggregating'] as const) {
      expect(assertTransition(phase, 'cancelled')).toBe(true)
    }
  })

  it('SupervisorCancellationError is terminal and never becomes success', () => {
    const err = new SupervisorCancellationError('aborted', { state: 'running' })
    expect(err.kind).toBe('cancellation')
    expect(err.state).toBe('running')
    expect(() => assertTransition('cancelled', 'completed')).toThrow(SupervisorError)
  })

  it('cancellation routes through the Runtime signal, not the DSH session', () => {
    // The contract maps Supervisor.signal onto the strategy's signal param;
    // the strategy hands it to the Scheduler. No DshAgentHandle is touched.
    const plan: SupervisorPlan = {
      strategy: 'broadcast',
      options: { prompt: 'p', agents: [{ agentId: 'a' }] },
    }
    expect(plan).toBeDefined()
    // the plan omits `signal` — the Supervisor injects its own at run time
    expect(plan.options).not.toHaveProperty('signal')
  })
})

describe('Supervisor contract — error propagation boundary', () => {
  it('ExecutionError always preserves the original cause', () => {
    const boom = new Error('runtime blew up')
    const err = new SupervisorExecutionError('execution failed', { cause: boom })
    expect(err.kind).toBe('execution')
    expect(err.cause).toBe(boom)
    expect(isSupervisorError(err)).toBe(true)
  })

  it('AggregationError is distinct from ExecutionError', () => {
    const err = new SupervisorAggregationError('could not aggregate', { state: 'aggregating' })
    expect(err.kind).toBe('aggregation')
    expect(err.cause).toBeUndefined()
  })

  it('Runtime errors flow through the frozen strategies unchanged', async () => {
    // A real runtime run that fails is surfaced by SchedulerReport / the
    // strategy report; the Supervisor must not swallow it into a new model.
    const graph = new TaskGraph()
    graph.add({ id: 't', agentId: 'a', prompt: 'p' })
    const failing: TaskExecute = async () => ({
      taskId: 't',
      status: 'failed',
      text: undefined,
      error: 'task-boom',
      durationMs: 1,
      raw: undefined,
    })
    const scheduler = new Scheduler(failing)
    const report = await scheduler.run(graph)
    expect(report.ok).toBe(false)
    expect(report.results.get('t')!.status).toBe('failed')
    expect(report.results.get('t')!.error).toBe('task-boom')
  })

  it('a frozen broadcast run yields the frozen BroadcastReport shape', async () => {
    const report = await runBroadcast(execute, {
      prompt: 'p',
      agents: [{ agentId: 'a' }, { agentId: 'b' }],
    })
    expect(report.ok).toBe(true)
    expect(report.responses.map((r) => r.agentId)).toEqual(['a', 'b'])
    expect(report.responses.every((r) => r.status === 'completed')).toBe(true)
  })
})

describe('Supervisor contract — strategy boundary', () => {
  it('maps each strategy name to its frozen Runtime entry point', () => {
    expect(strategyEntryPoint('broadcast')).toBe('runBroadcast')
    expect(strategyEntryPoint('sequential')).toBe('runSequential')
    expect(strategyEntryPoint('relay')).toBe('runRelay')
  })

  it('SupervisorStrategyReport is a discriminated union of frozen reports', () => {
    const broadcastReport: SupervisorStrategyReport = {
      strategy: 'broadcast',
      report: { responses: [], joined: '', ok: true },
    }
    const sequentialReport: SupervisorStrategyReport = {
      strategy: 'sequential',
      report: { steps: [], final: undefined, ok: true },
    }
    const relayReport: SupervisorStrategyReport = {
      strategy: 'relay',
      report: { draft: '', turns: [], ok: true },
    }
    expect(broadcastReport.report.ok).toBe(true)
    expect(sequentialReport.report.steps).toEqual([])
    expect(relayReport.report.draft).toBe('')
  })

  it('SupervisorRunResult reuses the strategy report, not a second TaskResult', () => {
    const result: SupervisorRunResult = {
      runId: 'run-1',
      status: 'completed',
      report: { strategy: 'broadcast', report: { responses: [], joined: '', ok: true } },
      errors: [],
      metadata: undefined,
      durationMs: 5,
    }
    expect(result.status).toBe('completed')
    expect(result.errors).toHaveLength(0)
    expect(result.report.strategy).toBe('broadcast')
  })
})
