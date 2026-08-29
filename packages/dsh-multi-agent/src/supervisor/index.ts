/**
 * Native Supervisor — export surface.
 *
 * Phase E1 ships the contract (types, error model, lifecycle rules, strategy
 * boundary). Phase E2 adds the executable Supervisor V1 (supervisor.ts) built
 * on top of that frozen contract and the frozen Runtime.
 *
 * The executable module has no Runtime side effects on import; it only
 * reaches the Runtime through the injected `execute: TaskExecute` at run time.
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

export { Supervisor, createSupervisor, validateSupervisorInput } from './supervisor'
export type { SupervisorDeps, SupervisorStrategyEntryPoints } from './supervisor'

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
