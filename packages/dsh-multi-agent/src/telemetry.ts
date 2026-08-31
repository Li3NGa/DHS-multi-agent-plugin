/** Lightweight, dependency-free observability for Native orchestration runs. */

export type OrchestrationEventKind =
  | 'run.started'
  | 'task.started'
  | 'task.completed'
  | 'task.failed'
  | 'task.cancelled'
  | 'task.blocked'
  | 'run.completed'

export interface OrchestrationEvent {
  readonly kind: OrchestrationEventKind
  readonly runId: string
  readonly timestamp: number
  readonly taskId?: string
  readonly agentId?: string
  readonly status?: string
  readonly durationMs?: number
  readonly error?: string
}

export interface OrchestrationObserver {
  readonly onEvent?: ((event: OrchestrationEvent) => void) | undefined
}

export function createRunId(): string {
  return `run-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`
}

export function emitEvent(observer: OrchestrationObserver | undefined, event: OrchestrationEvent): void {
  observer?.onEvent?.(event)
}
