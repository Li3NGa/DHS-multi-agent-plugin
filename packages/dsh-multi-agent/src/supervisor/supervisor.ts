/**
 * Native Supervisor — Phase E2: executable Supervisor V1.
 *
 * Implements the frozen E1 Supervisor Contract on top of the frozen Runtime.
 * The Supervisor ONLY orchestrates: validate input -> lifecycle -> dispatch to
 * a frozen Strategy -> aggregate the frozen report -> SupervisorRunResult.
 *
 * Runtime boundary: the Supervisor never touches `ctx.agents`, a DSH Session,
 * `session.events`, `followup()`, `agent.cancel()` or any LLM provider/adapter.
 * It reaches the Runtime exclusively through a frozen Strategy entry point,
 * which internally wires Scheduler -> AgentRunner via the injected
 * `execute: TaskExecute`. Nothing is copied or re-implemented here.
 *
 * Cancellation: an external AbortSignal is mapped onto the Runtime by aborting
 * a Supervisor-owned AbortController that is passed into the strategy. The
 * Runtime converges cooperatively; there is no second cancellation mechanism,
 * no polling and no sleep.
 *
 * Timeout: a whole-run ceiling that maps onto the SAME Runtime cancellation
 * (it aborts the same controller). There is deliberately NO second
 * AgentRunner timeout.
 */
import { runBroadcast, type BroadcastOptions, type BroadcastReport } from '../strategies/broadcast'
import { runRelay, type RelayOptions, type RelayReport } from '../strategies/relay'
import { runSequential, type SequentialOptions, type SequentialReport } from '../strategies/sequential'
import type { TaskExecute } from '../scheduler'
import {
  SupervisorCancellationError,
  SupervisorError,
  SupervisorExecutionError,
  SupervisorTimeoutError,
  SupervisorValidationError,
} from './errors'
import { assertTransition } from './lifecycle'
import { assertKnownStrategy } from './strategy'
import type {
  SupervisorPlan,
  SupervisorRunInput,
  SupervisorRunResult,
  SupervisorState,
  SupervisorStrategyReport,
} from './types'

/**
 * Frozen Strategy entry points the Supervisor may dispatch to. Provided as a
 * dependency so tests can inject faulty stand-ins for execution / aggregation
 * error paths WITHOUT changing the real strategies. Defaults to the frozen
 * runtime entry points.
 */
export interface SupervisorStrategyEntryPoints {
  readonly broadcast: (execute: TaskExecute, options: BroadcastOptions) => Promise<BroadcastReport>
  readonly sequential: (
    execute: TaskExecute,
    steps: readonly import('../strategies/sequential').SequentialStep[],
    options: SequentialOptions,
  ) => Promise<SequentialReport>
  readonly relay: (execute: TaskExecute, options: RelayOptions) => Promise<RelayReport>
}

/** Dependencies the Supervisor needs to reach the frozen Runtime. */
export interface SupervisorDeps {
  /** Frozen executor: Scheduler -> AgentRunner -> Real DSH wiring. */
  readonly execute: TaskExecute
  /** Strategy entry points; defaults to the frozen runtime implementations. */
  readonly strategies?: Partial<SupervisorStrategyEntryPoints>
}

/**
 * Structural validation of a SupervisorRunInput. Raises
 * SupervisorValidationError on the first illegal field. This is the ONLY
 * validation the Supervisor performs: it never calls an LLM, never repairs or
 * re-plans, and never picks agents.
 */
export function validateSupervisorInput(input: SupervisorRunInput): SupervisorPlan {
  const state: SupervisorState = 'validating'
  if (input === null || typeof input !== 'object') {
    throw new SupervisorValidationError('supervisor input must be an object', { state })
  }
  if (typeof input.runId !== 'string' || input.runId.length === 0) {
    throw new SupervisorValidationError('runId must be a non-empty string', { state })
  }
  if (typeof input.input !== 'string' || input.input.length === 0) {
    throw new SupervisorValidationError('input must be a non-empty string', { state })
  }
  if (input.plan === null || typeof input.plan !== 'object') {
    throw new SupervisorValidationError('plan is required', { state })
  }
  const plan = input.plan
  try {
    assertKnownStrategy(plan.strategy)
  } catch {
    throw new SupervisorValidationError(
      `unknown strategy: '${String((plan as { readonly strategy?: unknown }).strategy)}'`,
      { state },
    )
  }
  switch (plan.strategy) {
    case 'broadcast':
      validateBroadcastOptions(plan.options, state)
      break
    case 'sequential':
      validateSequentialPlan(plan.steps, state)
      break
    case 'relay':
      validateRelayOptions(plan.options, state)
      break
  }
  if (input.metadata !== undefined && (input.metadata === null || typeof input.metadata !== 'object')) {
    throw new SupervisorValidationError('metadata must be a record or undefined', { state })
  }
  return plan
}

function validateBroadcastOptions(options: Omit<BroadcastOptions, 'signal'>, state: SupervisorState): void {
  if (options === null || typeof options !== 'object') {
    throw new SupervisorValidationError('broadcast options must be an object', { state })
  }
  if (typeof options.prompt !== 'string' || options.prompt.length === 0) {
    throw new SupervisorValidationError('broadcast prompt must be a non-empty string', { state })
  }
  if (!Array.isArray(options.agents)) {
    throw new SupervisorValidationError('broadcast agents must be an array', { state })
  }
  const ids = new Set<string>()
  for (const agent of options.agents) {
    if (agent === null || typeof agent !== 'object') {
      throw new SupervisorValidationError('broadcast agent must be an object', { state })
    }
    if (typeof agent.agentId !== 'string' || agent.agentId.length === 0) {
      throw new SupervisorValidationError('broadcast agentId must be a non-empty string', { state })
    }
    if (ids.has(agent.agentId)) {
      throw new SupervisorValidationError(`duplicate broadcast agentId: '${agent.agentId}'`, { state })
    }
    ids.add(agent.agentId)
  }
}

function validateSequentialPlan(
  steps: readonly import('../strategies/sequential').SequentialStep[],
  state: SupervisorState,
): void {
  if (!Array.isArray(steps)) {
    throw new SupervisorValidationError('sequential steps must be an array', { state })
  }
  for (const step of steps) {
    if (step === null || typeof step !== 'object') {
      throw new SupervisorValidationError('sequential step must be an object', { state })
    }
    if (typeof step.agentId !== 'string' || step.agentId.length === 0) {
      throw new SupervisorValidationError('sequential step agentId must be a non-empty string', { state })
    }
  }
}

function validateRelayOptions(options: Omit<RelayOptions, 'signal'>, state: SupervisorState): void {
  if (options === null || typeof options !== 'object') {
    throw new SupervisorValidationError('relay options must be an object', { state })
  }
  if (typeof options.prompt !== 'string' || options.prompt.length === 0) {
    throw new SupervisorValidationError('relay prompt must be a non-empty string', { state })
  }
  if (!Array.isArray(options.steps)) {
    throw new SupervisorValidationError('relay steps must be an array', { state })
  }
  for (const step of options.steps) {
    if (step === null || typeof step !== 'object') {
      throw new SupervisorValidationError('relay step must be an object', { state })
    }
    if (typeof step.agentId !== 'string' || step.agentId.length === 0) {
      throw new SupervisorValidationError('relay step agentId must be a non-empty string', { state })
    }
  }
}

/**
 * Executable Supervisor V1. One instance may run multiple runs sequentially;
 * each run owns a fresh lifecycle and its own AbortController.
 */
export class Supervisor {
  readonly #execute: TaskExecute
  readonly #strategies: SupervisorStrategyEntryPoints
  #state: SupervisorState = 'created'

  constructor(deps: SupervisorDeps) {
    this.#execute = deps.execute
    this.#strategies = {
      broadcast: deps.strategies?.broadcast ?? runBroadcast,
      sequential: deps.strategies?.sequential ?? runSequential,
      relay: deps.strategies?.relay ?? runRelay,
    }
  }

  /** Current lifecycle state (for observability / tests). */
  get state(): SupervisorState {
    return this.#state
  }

  #move(to: SupervisorState): void {
    assertTransition(this.#state, to)
    this.#state = to
  }

  /**
   * Run one plan end-to-end and return the aggregated result.
   *
   * Lifecycle:
   *   created -> validating -> scheduled -> running -> aggregating -> terminal
   * where terminal is `completed` / `failed` (report not ok), `cancelled`
   * (external AbortSignal) or `timeout` (whole-run ceiling).
   *
   * Errors: a malformed input raises SupervisorValidationError; a Runtime /
   * strategy failure raises SupervisorExecutionError (original preserved in
   * `cause`); cancellation / timeout map to SupervisorCancellationError /
   * SupervisorTimeoutError. Nothing is swallowed.
   */
  async run(input: SupervisorRunInput): Promise<SupervisorRunResult> {
    const startedAt = Date.now()
    this.#state = 'created'

    this.#move('validating')
    let plan: SupervisorPlan
    try {
      plan = validateSupervisorInput(input)
    } catch (error) {
      // validation rejects the run: validating -> failed, then re-raise
      this.#move('failed')
      throw error
    }
    this.#move('scheduled')
    this.#move('running')

    const controller = new AbortController()
    let cancelled = false
    let timedOut = false
    const onExternalAbort = (): void => {
      cancelled = true
      controller.abort()
    }
    if (input.signal !== undefined) {
      if (input.signal.aborted) {
        onExternalAbort()
      } else {
        input.signal.addEventListener('abort', onExternalAbort, { once: true })
      }
    }
    const timer =
      input.timeoutMs !== undefined && input.timeoutMs > 0
        ? setTimeout(() => {
            timedOut = true
            controller.abort()
          }, input.timeoutMs)
        : undefined

    try {
      let strategyReport: SupervisorStrategyReport
      try {
        strategyReport = await this.#dispatch(plan, controller.signal)
      } catch (error) {
        this.#move(timedOut ? 'timeout' : cancelled ? 'cancelled' : 'failed')
        if (timedOut) {
          throw new SupervisorTimeoutError(`run '${input.runId}' timed out`, {
            cause: error,
            state: this.#state,
          })
        }
        if (cancelled) {
          throw new SupervisorCancellationError(`run '${input.runId}' cancelled`, {
            cause: error,
            state: this.#state,
          })
        }
        throw new SupervisorExecutionError(`run '${input.runId}' failed`, {
          cause: error,
          state: this.#state,
        })
      }

      this.#move('aggregating')
      return this.#aggregate(input, strategyReport, startedAt, { cancelled, timedOut })
    } finally {
      if (timer !== undefined) clearTimeout(timer)
      if (input.signal !== undefined && !input.signal.aborted) {
        input.signal.removeEventListener('abort', onExternalAbort)
      }
    }
  }

  /** Dispatch to a frozen strategy entry point; never copies its internals. */
  async #dispatch(plan: SupervisorPlan, signal: AbortSignal): Promise<SupervisorStrategyReport> {
    switch (plan.strategy) {
      case 'broadcast':
        return {
          strategy: 'broadcast',
          report: await this.#strategies.broadcast(this.#execute, { ...plan.options, signal }),
        }
      case 'sequential':
        return {
          strategy: 'sequential',
          report: await this.#strategies.sequential(this.#execute, plan.steps, {
            ...plan.options,
            signal,
          }),
        }
      case 'relay':
        return {
          strategy: 'relay',
          report: await this.#strategies.relay(this.#execute, { ...plan.options, signal }),
        }
    }
  }

  /** Turn the frozen strategy report into a SupervisorRunResult. */
  #aggregate(
    input: SupervisorRunInput,
    strategyReport: SupervisorStrategyReport,
    startedAt: number,
    flags: { readonly cancelled: boolean; readonly timedOut: boolean },
  ): SupervisorRunResult {
    const status =
      flags.timedOut ? ('timeout' as const) : flags.cancelled ? ('cancelled' as const) : strategyReport.report.ok ? ('completed' as const) : ('failed' as const)
    this.#move(status)

    const errors: SupervisorError[] = []
    if (status === 'timeout') {
      errors.push(new SupervisorTimeoutError(`run '${input.runId}' timed out`, { state: this.#state }))
    } else if (status === 'cancelled') {
      errors.push(
        new SupervisorCancellationError(`run '${input.runId}' cancelled`, { state: this.#state }),
      )
    }

    return {
      runId: input.runId,
      status,
      report: strategyReport,
      errors,
      metadata: input.metadata,
      durationMs: Date.now() - startedAt,
    }
  }
}

/** Convenience factory. */
export function createSupervisor(deps: SupervisorDeps): Supervisor {
  return new Supervisor(deps)
}
