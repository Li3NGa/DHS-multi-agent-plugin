/**
 * DSH API ports — calibrated against the DeepSeek Harness package surface
 * used by the verified Native smoke suite (Cordis 4.0.1 and the unified
 * 0.1.1-rc.2 DSH package line).
 *
 * Only the surface this runtime uses is declared; the real Agent satisfies
 * these structural types. Key real-API facts this port encodes:
 *
 * - `followup(message: UserMessage): void` is synchronous and returns
 *   nothing: the reply never comes back through followup. Results live in
 *   `agent.session.events` (an append-only, seq-contiguous log where
 *   `seq === index`), as `assistant/message` / `tool/call` / `tool/result`
 *   / `turn/end` events scoped by turn and step.
 * - Task correlation: recording `session.events.length` before followup()
 *   and slicing after `whenIdle()` yields exactly this task's events — a
 *   later task physically cannot read an earlier task's assistant message.
 * - `whenIdle(): Promise<void>` resolves at whole-agent quiescence.
 * - `cancel(cause: AgentCancelCause, options?)` is the host's real
 *   cancellation mechanism; `{ kind: 'hook', reason }` is the plugin-facing
 *   cause. A cancelled turn finalizes its streamed prefix as
 *   `assistant/message` with `interrupted: true` and closes with
 *   `turn/end { reason: { kind: 'aborted', ... } }`.
 */
import { SessionId } from '@deepseek-ai/dsh-session'
import type { AgentCancelCause, SessionEvent, UserMessage } from '@deepseek-ai/dsh-session'

export type { AgentCancelCause, SessionEvent, UserMessage }

/** The subset of the real DSH Agent this runtime drives. */
export interface DshAgentHandle {
  /** Stable identity (a DSH SessionId); tasks address agents by this id. */
  readonly id: string

  /** Live event log; append-only with `seq === index`. */
  readonly session: { readonly events: readonly SessionEvent[] }

  /** Queue one ordinary follow-up turn (sole message of its own turn). */
  followup(message: UserMessage): void

  /** Resolve after the agent reaches quiescence (no active driver). */
  whenIdle(): Promise<void>

  /** Abort the active turn / clear queued work — the host cancel path. */
  cancel(cause: AgentCancelCause, options?: unknown): void
}

/** Registry lookup over `ctx.agents` (AgentRegistry.get by session id). */
export interface DshAgentLookup {
  get(agentId: SessionId): DshAgentHandle | undefined
}

/** Resolve a plain-string task agentId through the registry. */
export function lookupAgent(
  registry: DshAgentLookup,
  agentId: string,
): DshAgentHandle | undefined {
  return registry.get(SessionId(agentId))
}

/**
 * The plugin context DSH hands to `apply(ctx, config)`: the cordis Context
 * carries far more; only what this plugin uses is declared here.
 * `reflect.provide(name, value)` is the sanctioned way a function plugin
 * exposes a service (auto-unloaded with the plugin's fiber).
 */
export interface DshContext {
  readonly agents: DshAgentLookup
  readonly reflect?: {
    provide(name: string, value: unknown): unknown
  }
}
