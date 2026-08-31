/**
 * Native Planner — Phase E3 Contract (types only).
 *
 * The Planner layer sits in front of the frozen E1 Supervisor and E2
 * Supervisor V1. It turns raw user input into a validated, agent-routed plan
 * that the Supervisor can execute.
 *
 * Runtime boundary: this file only declares types. It reuses the frozen
 * Runtime types where they already exist (`Task`, `SupervisorPlan`,
 * `SupervisorRunInput`) and does NOT redefine the Supervisor. It introduces
 * ONLY the planner-layer models that the Runtime has no equivalent for:
 * agent capability routing and strategy-agnostic planned tasks.
 *
 * Contract sections:
 *   - AgentDescriptor / capability model
 *   - PlanTask / PlannerPlan (strategy-agnostic plan)
 *   - PlanSource (injectable planner hook)
 *   - ValidatedPlan / PlanIssue (validator output)
 *   - RoutedPlan / RouteAssignment (router output)
 *   - Planner integration extension points
 */
import type { SupervisorStrategy } from '../supervisor'

/** A routable agent known to the runtime's ctx.agents registry. */
export interface AgentDescriptor {
  readonly id: string
  /** Capability tags the agent declares; used for capability routing. */
  readonly capabilities: readonly string[]
}

/**
 * A strategy-agnostic planned task (the Planner's unit of output).
 *
 * `agentId` is optional: if absent, the Router assigns one via capability
 * matching / round-robin. `requiredCapabilities` drives that assignment.
 */
export interface PlanTask {
  readonly id: string
  readonly prompt: string
  /** Preferred (explicit) agent. The Router honours this if resolvable. */
  readonly agentId?: string
  /** Capability tags the task requires of its agent. */
  readonly requiredCapabilities?: readonly string[]
  /** Task ids that must complete before this task. */
  readonly dependsOn?: readonly string[]
  readonly timeoutMs?: number
  readonly metadata?: Readonly<Record<string, unknown>>
}

/** The Planner's output: a list of planned tasks (no fixed strategy). */
export interface PlannerPlan {
  readonly tasks: readonly PlanTask[]
}

/**
 * How a Planner's raw output was parsed. `json` = structured task array;
 * `lines` = one-task-per-line fallback.
 */
export type PlanFormat = 'json' | 'lines'

/**
 * Injectable planner hook: turns the user prompt into raw plan text that
 * `PlannerV1` parses. In tests this is a scripted function; in production it
 * wraps a real model call (adapter route) but the Planner itself never calls
 * the model directly — this keeps the planner deterministic and testable.
 */
export type PlanSource = (prompt: string) => Promise<string>

/** What PlannerV1 produces: a parsed plan plus provenance notes. */
export interface PlannerResult {
  readonly plan: PlannerPlan
  readonly format: PlanFormat
  /** Human/program-readable notes about how the plan was derived. */
  readonly notes: readonly string[]
}

/** Severity of a plan-validator finding. */
export type PlanIssueSeverity = 'error' | 'warning'

/** A single validator finding on a plan. */
export interface PlanIssue {
  readonly severity: PlanIssueSeverity
  readonly code:
    | 'empty-plan'
    | 'duplicate-task-id'
    | 'empty-task-id'
    | 'missing-prompt'
    | 'self-dependency'
    | 'unknown-dependency'
    | 'cycle'
    | 'unknown-agent'
    | 'unsupported-capability'
    | 'unroutable-task'
  readonly message: string
  readonly taskId?: string
}

/**
 * Validator output: the plan (possibly repaired in place) plus the issues
 * found. `repair` is true when the validator applied a semantically-safe
 * repair (re-route unknown agent, drop unsupported capability).
 */
export interface ValidatedPlan {
  readonly plan: PlannerPlan
  readonly issues: readonly PlanIssue[]
  readonly repaired: boolean
}

/** One concrete agent assignment produced by the Router. */
export interface RouteAssignment {
  readonly taskId: string
  readonly agentId: string
  /** Why this agent was chosen (explicit / capability / round-robin). */
  readonly reason: 'explicit' | 'capability' | 'round-robin'
}

/** A fully routed task: every task now has a concrete agentId. */
export interface RoutedTask extends Omit<PlanTask, 'agentId' | 'requiredCapabilities'> {
  readonly agentId: string
}

/** Router output: routed tasks plus the assignment trail. */
export interface RoutedPlan {
  readonly tasks: readonly RoutedTask[]
  readonly assignments: readonly RouteAssignment[]
}

/**
 * Strategy hint used by the Supervisor integration when mapping a planned
 * task list onto the frozen SupervisorPlan. Defaults to `sequential` (the
 * most general linear mapping of a dependency-ordered plan).
 */
export type PlanExecutionStrategy = SupervisorStrategy

/** Result of the end-to-end Planner -> Supervisor integration entry point. */
export interface PlannedExecutionResult {
  /** Parsed plan (before validation / repair). */
  readonly plan: PlannerPlan
  /** How the raw plan text was parsed. */
  readonly format: PlanFormat
  /** Validated (+ repaired) plan and its issue trail. */
  readonly validated: ValidatedPlan
  /** Agent-routed plan with the assignment trail. */
  readonly routed: RoutedPlan
  /** Strategy the integration mapped the plan onto. */
  readonly strategy: PlanExecutionStrategy
  /** The exact SupervisorRunInput handed to Supervisor.run. */
  readonly supervisorInput: import('../supervisor').SupervisorRunInput
  /** The Supervisor's aggregated run result. */
  readonly result: import('../supervisor').SupervisorRunResult
}
