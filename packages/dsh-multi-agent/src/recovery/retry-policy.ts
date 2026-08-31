/**
 * Native Recovery — minimal bounded Retry Policy.
 *
 * Finite by construction: `maxAttempts` is a positive integer (default 3)
 * and every dispatch is guarded by canAttempt(). Infinite retry is
 * impossible without bypassing this class. V1 keeps delay deterministic and
 * zero by default; no exponential backoff, persistence or background workers.
 */
import type { RecoveryPolicyOptions } from './types'

function normalizeInt(value: unknown, min: number, name: string): number {
  if (typeof value !== 'number' || !Number.isInteger(value) || value < min) {
    throw new TypeError(`${name} must be an integer >= ${min}`)
  }
  return value
}

export class RetryPolicy {
  static readonly DEFAULT_MAX_ATTEMPTS = 3
  static readonly DEFAULT_MAX_REPLANS = 2

  /** Max executions for one logical run (>= 1, finite). */
  readonly maxAttempts: number
  /** Max deterministic replans per run (>= 0, finite). */
  readonly maxReplans: number
  /** Deterministic inter-attempt delay in ms (>= 0). */
  readonly delayMs: number

  constructor(options: RecoveryPolicyOptions = {}) {
    this.maxAttempts =
      options.maxAttempts === undefined
        ? RetryPolicy.DEFAULT_MAX_ATTEMPTS
        : normalizeInt(options.maxAttempts, 1, 'maxAttempts')
    this.maxReplans =
      options.maxReplans === undefined
        ? RetryPolicy.DEFAULT_MAX_REPLANS
        : normalizeInt(options.maxReplans, 0, 'maxReplans')
    if (
      options.delayMs !== undefined &&
      (typeof options.delayMs !== 'number' || !Number.isFinite(options.delayMs) || options.delayMs < 0)
    ) {
      throw new TypeError('delayMs must be a finite number >= 0')
    }
    this.delayMs = options.delayMs ?? 0
  }

  /** True when execution number `attempt` (1-based) is still budgeted. */
  canAttempt(attempt: number): boolean {
    return Number.isInteger(attempt) && attempt >= 1 && attempt <= this.maxAttempts
  }

  /** True when another replan is allowed (`replansUsed` so far). */
  canReplan(replansUsed: number): boolean {
    return replansUsed < this.maxReplans
  }
}

/**
 * Deterministic bounded wait. A caller abort resolves the wait immediately;
 * the RecoveryManager checks the signal before the next dispatch and exits
 * without consuming another attempt.
 */
export function delay(ms: number, signal?: AbortSignal): Promise<void> {
  if (ms <= 0 || signal?.aborted) return Promise.resolve()
  return new Promise<void>((resolve) => {
    let timer: ReturnType<typeof setTimeout> | undefined
    const cleanup = (): void => {
      if (timer !== undefined) clearTimeout(timer)
      signal?.removeEventListener('abort', onAbort)
    }
    const finish = (): void => {
      cleanup()
      resolve()
    }
    const onAbort = (): void => finish()
    timer = setTimeout(finish, ms)
    signal?.addEventListener('abort', onAbort, { once: true })
    if (signal?.aborted) finish()
  })
}
