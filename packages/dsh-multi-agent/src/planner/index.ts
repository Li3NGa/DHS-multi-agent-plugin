/**
 * Native Planner — E3/E5 export surface.
 *
 * Planner Contract + Planner V1 + Plan Validator + Agent Router +
 * Supervisor Integration + direct arbitrary-DAG execution.
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
  PlanDagRunOptions,
  PlannedDagExecutionResult,
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
  planAndRunDag,
  createPlanPipeline,
} from './integration'
export type { PlanPipelineDeps, PlanRunOptions } from './integration'
