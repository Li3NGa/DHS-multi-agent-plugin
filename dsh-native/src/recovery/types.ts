/**
 * Native Recovery — Phase E4 Contract (types only).
 *
 * E4 answers one question: "what does the system do after a task fails?"
 *
 *   execution -> failure -> classify -> retry / repair / replan / abort
 *     -> validate -> route -> supervisor -> execution
 *
 * Boundary rules (Phase E4 V1):
 * - Deterministic only. No LLM, no network, no persistence, no background
 *   workers, no unbounded retry/replan.
 * - The frozen Supervisor executes exactly one legal run; recovery decisions
 *   live in the RecoveryManager, never inside the Supervisor.
 * - Raw runtime state (session.events) never reaches the planner / repair /
 *   replan layers; they see only the FailureRecord summaries defined here.
 */
import type { AgentDescriptor } from '../planner/types'
import type { SupervisorRunResult } from '../supervisor'

/** Machine-readable failure classes (Phase E4 Failure Model). */
export type FailureCode =
  | 'VALIDATION_ERROR'
  | 'ROUTING_ERROR'
  | 'TASK_ERROR'
  | 'TIMEOUT'
  | 'CANCELLED'
  | 'DEPENDENCY_FAILURE'
  | 'AGENT_UNAVAILABLE'
  | 'STRATEGY_ERROR'
  | 'RUNTIME_ERROR'

/** What a failure class allows the RecoveryManager to do about it. */
export interface Recoverability {
  /** Re-execute the same plan with attempt+1. */
  readonly retryable: boolean
  /** Locally fix the plan without changing task semantics (e.g. re-route). */
  readonly repairable: boolean
  /** Produce a NEW (semantically smaller) plan deterministically. */
  readonly replanable: boolean
  /** Terminal: no automatic recovery may be attempted at all. */
  readonly fatal: boolean
}

/** One failed task extracted from a strategy/scheduler report. */
export interface TaskFailureRef {
  readonly taskId: string
  readonly agentId: string | undefined
  readonly code: FailureCode
  readonly message: string
}

/**
 * A classified failure. Every recovery decision consumes this shape —
 * callers never string-match raw errors.
 *
 * The original error is preserved in `cause` and is never swallowed.
 */
export interface FailureRecord {
  readonly code: FailureCode
  readonly message: string
  readonly cause?: unknown
  /** Primary failed task id, when known. */
  readonly taskId?: string
  /** Agent involved in the failure, when known. */
  readonly agentId?: string
  /** 1-based execution attempt that produced this failure. */
  readonly attempt: number
  readonly recoverability: Recoverability
  /** ISO-8601 timestamp of classification. */
  readonly timestamp: string
  /** All per-task failures observed on the run (multi-task reports). */
  readonly taskFailures?: readonly TaskFailureRef[]
  /** True when the failure came from a thrown error instead of a result. */
  readonly thrown?: boolean
}

/** What Recovery needs to know to repair / replan (no session state). */
export interface RecoveryExecutionContext {
  readonly runId: string
  /** Stable identity of the plan being executed. */
  readonly planId: string
  /** 1-based attempt that just failed. */
  readonly attempt: number
  readonly completedTaskIds: readonly string[]
  readonly failedTaskIds: readonly string[]
  readonly previousFailures: readonly FailureRecord[]
  readonly availableAgents: readonly AgentDescriptor[]
}

/** Deterministic recovery actions (phase contract, decision section). */
export type RecoveryDecision =
  | 'retry'
  | 'repair'
  | 'replan'
  | 'abort'
  | 'completed'
  | 'failed'

/** Finite recovery budget. Both limits MUST be finite. */
export interface RecoveryPolicyOptions {
  /** Max executions for one logical run (integer >= 1). Default 3. */
  readonly maxAttempts?: number
  /** Max deterministic replans per run (integer >= 0). Default 2. */
  readonly maxReplans?: number
  /** Deterministic delay between attempts in ms (>= 0). Default 0. */
  readonly delayMs?: number
}

/** Options for one RecoveryManager.run call. */
export interface RecoveryRunOptions {
  readonly runId: string
  /** User intent / entry prompt (opaque; passed through to Supervisor). */
  readonly input: string
  /** Strategy mapping for the plan (default 'sequential'). */
  readonly strategy?: 'broadcast' | 'sequential' | 'relay'
  readonly timeoutMs?: number
  readonly signal?: AbortSignal
  readonly metadata?: Readonly<Record<string, unknown>>
}

/** Terminal outcome of one recovered run. */
export interface RecoveryRunResult {
  readonly runId: string
  readonly status: 'completed' | 'failed' | 'cancelled' | 'timeout'
  /** Executions performed (1-based count of dispatched attempts). */
  readonly attempts: number
  readonly repairsUsed: number
  readonly replansUsed: number
  /** Chronological failure chain (never truncated). */
  readonly failures: readonly FailureRecord[]
  /** Chronological decision trail, including the final one. */
  readonly decisions: readonly RecoveryDecision[]
  /** Last Supervisor result when at least one attempt ran. */
  readonly lastResult: SupervisorRunResult | undefined
}
