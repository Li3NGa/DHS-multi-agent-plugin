/**
 * DSH API ports.
 *
 * ⚠ VERIFICATION REQUIRED: these structural interfaces model the DSH
 * (DeepSeek Harness) surface this plugin is allowed to use -
 * `ctx.agents`, `agent.followup()`, `agent.whenIdle()` and session
 * events. The real DSH type definitions were not available in this
 * repository when this module was written, so the ports below are the
 * single adjustment point: when the actual DSH package provides types,
 * align them here (and in `normalizeReply` in runner.ts) instead of
 * spreading DSH assumptions across the codebase.
 *
 * The runtime (Task / TaskGraph / Scheduler) deliberately depends only
 * on these ports and on plain functions, never on a concrete DSH client.
 */

/**
 * A reply from an agent. The runner normalizes the shapes seen in the
 * DSH result channel into plain text; unknown shapes fall back to
 * `String(reply)` with the raw value preserved on the outcome.
 */
export type DshAgentReply =
  | string
  | { readonly content?: unknown; readonly text?: unknown }
  | readonly unknown[]

export interface DshAgent {
  /** Stable identifier inside the harness. */
  readonly id: string

  /**
   * Send a follow-up prompt to the agent and await its turn. Depending on
   * the real DSH API this may resolve with the final text, a structured
   * reply object, or a list of session events.
   */
  followup(prompt: string, options?: Record<string, unknown>): Promise<DshAgentReply>

  /**
   * Wait until the agent has drained its loop (pending tool calls etc.).
   * Optional: when present the runner awaits it after followup() so tool
   * results are included before the task is settled.
   */
  whenIdle?(): Promise<unknown>
}

export interface DshAgentLookup {
  get(agentId: string): DshAgent | undefined
}

/** Cordis-style lifecycle events the plugin listens to (subset). */
export interface DshLifecycle {
  on(event: 'ready' | 'dispose', listener: () => void): unknown
}

/**
 * The plugin context DSH hands to `apply(ctx, config)`. Only the surface
 * this plugin actually uses is declared.
 */
export interface DshContext extends DshLifecycle {
  readonly agents: DshAgentLookup
}
