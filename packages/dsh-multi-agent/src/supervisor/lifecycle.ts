/**
 * Native Supervisor — Phase E1 Lifecycle contract (pure, no runtime).
 *
 * Pins the legal state machine of a Supervisor run. This is contract-only:
 * it validates transitions without executing anything, so E2 can rely on it
 * as the single source of truth for lifecycle legality.
 *
 * States:
 *   created -> validating -> scheduled -> running -> aggregating -> completed
 *
 * Abnormal terminal states (only reachable from the phases below):
 *   failed      (ExecutionError / AggregationError)
 *   cancelled   (CancellationError — external AbortSignal)
 *   timeout     (TimeoutError — whole-run ceiling)
 *
 * Forbidden transitions (never legal):
 *   - completing before created/validating
 *   - running before scheduled
 *   - any transition out of a terminal state (completed/failed/cancelled/timeout)
 *   - backwards transitions
 */
import { SupervisorValidationError } from './errors'
import type { SupervisorState, SupervisorRunStatus } from './types'

/** The forward (happy-path) chain of phases. */
export const PHASE_ORDER: readonly SupervisorState[] = [
  'created',
  'validating',
  'scheduled',
  'running',
  'aggregating',
  'completed',
]

/** Terminal statuses; nothing may leave them. */
export const TERMINAL_STATUSES: ReadonlySet<SupervisorRunStatus> = new Set([
  'completed',
  'failed',
  'cancelled',
  'timeout',
])

const TERMINAL_AS_STATE: ReadonlySet<SupervisorState> = new Set([
  'completed',
  'failed',
  'cancelled',
  'timeout',
])

/** True when a state is terminal (no further transitions allowed). */
export function isTerminalState(state: SupervisorState): boolean {
  return TERMINAL_AS_STATE.has(state)
}

/**
 * Legal transitions. Only forward phase moves and phase -> terminal are
 * allowed. `partial` is a terminal roll-up, so it is legal as a transition
 * target from `aggregating` only (reserved for future policy).
 */
const TRANSITIONS: ReadonlyMap<SupervisorState, ReadonlySet<SupervisorState>> = new Map<
  SupervisorState,
  ReadonlySet<SupervisorState>
>([
  ['created', new Set<SupervisorState>(['validating', 'cancelled'])],
  ['validating', new Set<SupervisorState>(['scheduled', 'failed', 'cancelled'])],
  ['scheduled', new Set<SupervisorState>(['running', 'failed', 'cancelled', 'timeout'])],
  ['running', new Set<SupervisorState>(['aggregating', 'failed', 'cancelled', 'timeout'])],
  ['aggregating', new Set<SupervisorState>(['completed', 'failed', 'partial', 'cancelled', 'timeout'])],
])

/**
 * Validate a transition. Throws SupervisorValidationError on an illegal
 * move; returns true for a legal one. Contract-only — never mutates.
 */
export function assertTransition(from: SupervisorState, to: SupervisorState): boolean {
  if (from === to) {
    throw new SupervisorValidationError(
      `illegal lifecycle transition: '${from}' -> '${to}' (no-op transition is not allowed)`,
      { state: from },
    )
  }
  if (isTerminalState(from)) {
    throw new SupervisorValidationError(
      `illegal lifecycle transition: cannot leave terminal state '${from}'`,
      { state: from },
    )
  }
  const allowed = TRANSITIONS.get(from)
  if (!allowed || !allowed.has(to)) {
    throw new SupervisorValidationError(
      `illegal lifecycle transition: '${from}' -> '${to}'`,
      { state: from },
    )
  }
  return true
}
