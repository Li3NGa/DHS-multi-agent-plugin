/**
 * Native Recovery — Phase E4 export surface.
 *
 * Failure Model + Classification + RetryPolicy + Repair V1 + Replan V1 +
 * RecoveryManager. Deterministic only; sits around the frozen Supervisor /
 * Runtime and reuses the E3 Validator / Router for every candidate plan.
 */
export type {
  FailureCode,
  Recoverability,
  TaskFailureRef,
  FailureRecord,
  RecoveryExecutionContext,
  RecoveryDecision,
  RecoveryPolicyOptions,
  RecoveryRunOptions,
  RecoveryRunResult,
} from './types'

export { RECOVERABILITY, classifyThrown, classifyResult, extractTaskFailures, extractCompletedTaskIds } from './failure'
export { RetryPolicy, delay } from './retry-policy'
export type { PlanRepair, RepairRecord, AssignmentRepairResult } from './repair'
export { applyIssueRepairs, clearAgentAssignments } from './repair'
export type { ReplanRule, ReplanInput, ReplanResult } from './replanner'
export { deterministicReplan } from './replanner'
export { RecoveryManager, planId } from './manager'
export type { RecoveryManagerDeps } from './manager'
export { SingleFlightRecoveryManager, createSingleFlightRecoveryManager, createRecoveryManager } from './single-flight'
