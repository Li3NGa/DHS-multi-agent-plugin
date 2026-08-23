/**
 * Native Supervisor — Phase E1 Strategy boundary (contract only).
 *
 * The Supervisor reaches strategies ONLY through the frozen Runtime entry
 * points (`runBroadcast` / `runSequential` / `runRelay` from index.ts) and
 * the frozen option/report types. It never copies a strategy's internals.
 *
 * This module maps a {@link SupervisorPlan} to the exact Runtime call. It is
 * contract-only: it returns the resolved arguments but does not execute.
 */
import type { BroadcastOptions } from '../strategies/broadcast'
import type { SequentialOptions, SequentialStep } from '../strategies/sequential'
import type { RelayOptions } from '../strategies/relay'
import type { SupervisorPlan } from './types'

/**
 * Which frozen Runtime entry point a plan maps to and which frozen report
 * type it yields. Static boundary assertion — the Supervisor never copies
 * strategy internals, only dispatches to these entry points.
 */
export function strategyEntryPoint(strategy: SupervisorPlan['strategy']): string {
  switch (strategy) {
    case 'broadcast':
      return 'runBroadcast'
    case 'sequential':
      return 'runSequential'
    case 'relay':
      return 'runRelay'
  }
}

/** Re-export the frozen strategy option/step types used by the boundary. */
export type { BroadcastOptions, SequentialOptions, SequentialStep, RelayOptions }

/** Guard: never accept a plan whose strategy the Supervisor does not know. */
export function assertKnownStrategy(strategy: string): asserts strategy is SupervisorPlan['strategy'] {
  if (strategy !== 'broadcast' && strategy !== 'sequential' && strategy !== 'relay') {
    throw new TypeError(`unknown supervisor strategy: '${strategy}'`)
  }
}
