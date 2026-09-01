/** Production diagnostics built on the R9 observability contract. */
import type { MetricsSnapshot, ObservabilityEvent, RuntimeObserver } from './observability'
import { observe } from './observability'
import type { FailureCode, RecoveryDecision, RecoveryRunResult } from './recovery'

export interface FailureSummary {
  readonly at: string
  readonly attempt: number
  readonly code: FailureCode
  readonly taskId: string | undefined
  readonly agentId: string | undefined
}
export type RunInspectionStatus = RecoveryRunResult['status'] | 'running'
export interface RunInspection {
  readonly runId: string
  readonly status: RunInspectionStatus
  readonly startedAt: string
  readonly finishedAt: string | undefined
  readonly durationMs: number
  readonly attempts: number
  readonly repairsUsed: number
  readonly replansUsed: number
  readonly failureCount: number
  readonly failures: readonly FailureSummary[]
  readonly decisions: readonly RecoveryDecision[]
}
export type RuntimeHealthStatus = 'healthy' | 'degraded' | 'unhealthy'
export interface RuntimeHealthSnapshot {
  readonly status: RuntimeHealthStatus
  readonly checkedAt: string
  readonly uptimeMs: number
  readonly activeRuns: number
  readonly metrics: MetricsSnapshot
  readonly reasons: readonly string[]
}

export class RunRegistry {
  readonly #maxRuns: number
  readonly #runs = new Map<string, RunInspection>()
  constructor(maxRuns = 256) {
    if (!Number.isInteger(maxRuns) || maxRuns < 1) throw new RangeError('maxRuns must be a positive integer')
    this.#maxRuns = maxRuns
  }
  start(runId: string, at = new Date().toISOString()): void {
    this.#runs.delete(runId)
    this.#runs.set(runId, { runId, status: 'running', startedAt: at, finishedAt: undefined, durationMs: 0, attempts: 0, repairsUsed: 0, replansUsed: 0, failureCount: 0, failures: [], decisions: [] })
    this.#trim()
  }
  attempt(runId: string, attempt: number): void {
    const r = this.#runs.get(runId)
    if (r) this.#runs.set(runId, { ...r, attempts: Math.max(r.attempts, attempt) })
  }
  failure(runId: string, summary: FailureSummary): void {
    const r = this.#runs.get(runId)
    if (!r) return
    this.#runs.set(runId, { ...r, failureCount: r.failureCount + 1, failures: [...r.failures, summary], attempts: Math.max(r.attempts, summary.attempt) })
  }
  decision(runId: string, decision: RecoveryDecision): void {
    const r = this.#runs.get(runId)
    if (r) this.#runs.set(runId, { ...r, decisions: [...r.decisions, decision] })
  }
  finish(result: RecoveryRunResult, at = new Date().toISOString()): void {
    const previous = this.#runs.get(result.runId)
    const startedAt = previous?.startedAt ?? at
    const failures = result.failures.map(f => ({ at: f.timestamp, attempt: f.attempt, code: f.code, taskId: f.taskId, agentId: f.agentId }))
    this.#runs.set(result.runId, { runId: result.runId, status: result.status, startedAt, finishedAt: at, durationMs: Math.max(0, Date.parse(at) - Date.parse(startedAt)), attempts: result.attempts, repairsUsed: result.repairsUsed, replansUsed: result.replansUsed, failureCount: failures.length, failures, decisions: [...result.decisions] })
    this.#trim()
  }
  complete(runId: string, status: RunInspectionStatus, attempts: number, repairsUsed: number, replansUsed: number, at: string): void {
    const current = this.#runs.get(runId)
    if (!current) return
    this.#runs.set(runId, { ...current, status, finishedAt: at, durationMs: Math.max(0, Date.parse(at) - Date.parse(current.startedAt)), attempts, repairsUsed, replansUsed })
  }
  get(runId: string): RunInspection | undefined {
    const r = this.#runs.get(runId)
    return r ? { ...r, failures: [...r.failures], decisions: [...r.decisions] } : undefined
  }
  list(limit = 50): readonly RunInspection[] {
    const n = Math.max(1, Math.min(limit, this.#maxRuns))
    return [...this.#runs.values()].slice(-n).reverse().map(r => ({ ...r, failures: [...r.failures], decisions: [...r.decisions] }))
  }
  activeCount(): number {
    let n = 0
    for (const r of this.#runs.values()) if (r.status === 'running') n++
    return n
  }
  clear(): void { this.#runs.clear() }
  #trim(): void { while (this.#runs.size > this.#maxRuns) this.#runs.delete(this.#runs.keys().next().value!) }
}

export interface DiagnosticsOptions {
  readonly metrics: { snapshot(): MetricsSnapshot }
  readonly registry?: RunRegistry
  readonly observer?: RuntimeObserver
  readonly now?: () => number
  readonly startedAt?: number
}
export class RuntimeDiagnostics {
  readonly #metrics: DiagnosticsOptions['metrics']
  readonly #registry: RunRegistry
  readonly #observer: RuntimeObserver | undefined
  readonly #now: () => number
  readonly #startedAt: number
  constructor(options: DiagnosticsOptions) {
    this.#metrics = options.metrics
    this.#registry = options.registry ?? new RunRegistry()
    this.#observer = options.observer
    this.#now = options.now ?? Date.now
    this.#startedAt = options.startedAt ?? this.#now()
  }
  get registry(): RunRegistry { return this.#registry }
  startRun(runId: string): void { this.#registry.start(runId) }
  finishRun(result: RecoveryRunResult): void { this.#registry.finish(result) }
  inspect(runId: string): RunInspection | undefined { return this.#registry.get(runId) }
  recentRuns(limit = 50): readonly RunInspection[] { return this.#registry.list(limit) }
  health(): RuntimeHealthSnapshot {
    const metrics = this.#metrics.snapshot()
    const activeRuns = this.#registry.activeCount()
    const reasons: string[] = []
    if (activeRuns) reasons.push(`${activeRuns} run(s) active`)
    if (metrics.recoveryTimeouts) reasons.push(`${metrics.recoveryTimeouts} recovery timeout(s)`)
    if (metrics.tasksFailed > 0 && metrics.tasksCompleted === 0) reasons.push('no completed tasks with recorded failures')
    const status: RuntimeHealthStatus = metrics.recoveryTimeouts > 0 || (metrics.tasksFailed > 0 && metrics.tasksCompleted === 0)
      ? 'unhealthy'
      : activeRuns > 0 || metrics.tasksFailed > 0 || metrics.recoveryFailed > 0 ? 'degraded' : 'healthy'
    return { status, checkedAt: new Date(this.#now()).toISOString(), uptimeMs: Math.max(0, this.#now() - this.#startedAt), activeRuns, metrics, reasons }
  }
  observer(): RuntimeObserver {
    return event => { this.#consume(event); observe(this.#observer, event) }
  }
  #consume(event: ObservabilityEvent): void {
    switch (event.type) {
      case 'recovery.started': this.#registry.start(event.runId, event.at); break
      case 'recovery.attempt': this.#registry.attempt(event.runId, event.attempt); break
      case 'recovery.failure': this.#registry.failure(event.runId, { at: event.at, attempt: event.attempt, code: event.code, taskId: event.taskId, agentId: event.agentId }); break
      case 'recovery.decision': this.#registry.decision(event.runId, event.decision); break
      case 'recovery.finished': this.#registry.complete(event.runId, event.status, event.attempts, event.repairsUsed, event.replansUsed, event.at); break
      default: break
    }
  }
}
export function createRuntimeDiagnostics(options: DiagnosticsOptions): RuntimeDiagnostics { return new RuntimeDiagnostics(options) }
