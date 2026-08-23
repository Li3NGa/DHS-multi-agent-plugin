/**
 * Native Planner — Phase E3 export surface.
 *
 * Planner Contract + Planner V1 + Plan Validator + Agent Router +
 * Supervisor Integration. This layer sits in front of the frozen E1/E2
 * Supervisor and the frozen Runtime; it introduces no duplicate models and
 * reaches the Runtime only through `Supervisor.run`.
 */
export type {
  AgentDescriptor,
  PlanTask,
  PlannerPlan,
  PlanFormat,
  PlanSource,
  PlannerResult,
  PlanIssue,
  PlanIssueSeverity,
  ValidatedPlan,
  RouteAssignment,
  RoutedTask,
  RoutedPlan,
  PlanExecutionStrategy,
  PlannedExecutionResult,
} from './types'

export {
  PlannerError,
  PlanParseError,
  PlanValidationError,
  PlanRoutingError,
  PlanIntegrationError,
  isPlannerError,
} from './errors'

export { PlannerV1, createPlanner, parsePlanText } from './planner'
export type { PlannerDeps } from './planner'

export { PlanValidator, createPlanValidator } from './validator'
export type { PlanValidatorDeps } from './validator'

export { AgentRouter, createAgentRouter } from './router'
export type { AgentRouterDeps } from './router'

export {
  topologicalOrder,
  routedPlanToSupervisorPlan,
  planToSupervisorInput,
  planAndRun,
  createPlanPipeline,
} from './integration'
export type { PlanPipelineDeps, PlanRunOptions } from './integration'
