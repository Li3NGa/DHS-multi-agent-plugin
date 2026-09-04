import type { PlannerPlan } from '../planner'
import type { RecoveryRunOptions, RecoveryRunResult } from './types'
import { RecoveryManager, type RecoveryManagerDeps } from './manager'

/**
 * Public factory wrapper that prevents overlapping logical runs from sharing
 * one RecoveryManager/Supervisor instance.
 *
 * Recovery state is otherwise per-call; this guard exists because the manager
 * owns one Supervisor instance, whose lifecycle is intentionally single-flight.
 */
export class SingleFlightRecoveryManager extends RecoveryManager {
  #active = false

  override async run(plan: PlannerPlan, options: RecoveryRunOptions): Promise<RecoveryRunResult> {
    if (this.#active) {
      throw new Error('RecoveryManager is already running')
    }
    this.#active = true
    try {
      return await super.run(plan, options)
    } finally {
      this.#active = false
    }
  }
}

export function createSingleFlightRecoveryManager(deps: RecoveryManagerDeps): SingleFlightRecoveryManager {
  return new SingleFlightRecoveryManager(deps)
}

/** Backward-compatible public factory with single-flight protection. */
export function createRecoveryManager(deps: RecoveryManagerDeps): SingleFlightRecoveryManager {
  return createSingleFlightRecoveryManager(deps)
}
