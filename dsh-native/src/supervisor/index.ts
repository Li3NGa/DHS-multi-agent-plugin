/**
 * Native Supervisor — Phase E1 Contract export surface.
 *
 * Phase E1 ships ONLY the contract: types, error model, lifecycle rules and
 * strategy boundary. There is no executable Supervisor yet (Phase E2).
 *
 * These are pure type/rule modules with no Runtime side effects, so importing
 * them is safe and does not modify the frozen Runtime.
 */
export {
  SupervisorError,
  SupervisorValidationError,
  SupervisorExecutionError,
  SupervisorCancellationError,
  SupervisorTimeoutError,
  SupervisorAggregationError,
  isSupervisorError,
} from './errors'
export type { SupervisorErrorKind, SupervisorErrorFields } from './errors'

export {
  assertTransition,
  isTerminalState,
  PHASE_ORDER,
  TERMINAL_STATUSES,
} from './lifecycle'

export { strategyEntryPoint, assertKnownStrategy } from './strategy'
export type { BroadcastOptions, SequentialOptions, SequentialStep, RelayOptions } from './strategy'

export type {
  SupervisorPlan,
  SupervisorStrategy,
  SupervisorStrategyReport,
  SupervisorRunStatus,
  SupervisorPhase,
  SupervisorState,
  SupervisorRunInput,
  SupervisorRunResult,
  SupervisorSchedulerReport,
} from './types'
