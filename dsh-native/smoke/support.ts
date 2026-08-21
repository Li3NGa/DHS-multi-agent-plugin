/**
 * Real-harness smoke support: boots the REAL DeepSeek Harness runtime
 * (cordis Context + dsh-llm / dsh-session / dsh-system-prompt / dsh-tools /
 * dsh-agent / dsh-agent-loop) and registers a scripted LLM adapter through
 * the real `ctx.llm.registerAdapter` path — the same pattern DSH's own
 * upstream tests use. Nothing here mocks the DSH API: agents, sessions,
 * followup(), whenIdle(), cancel() and session events are all real; only
 * the model endpoint is scripted (no API key required).
 */
import { Context } from '@deepseek-ai/cordis'
import AgentRegistry from '@deepseek-ai/dsh-agent'
import AgentLoop from '@deepseek-ai/dsh-agent-loop'
import { LlmAdapter } from '@deepseek-ai/dsh-llm'
import type { GenerateOptions, LlmResolvedModelInfo, StreamChunk } from '@deepseek-ai/dsh-llm'
import LlmRuntime from '@deepseek-ai/dsh-llm'
import SessionStore, { SessionId } from '@deepseek-ai/dsh-session'
import SystemPrompt from '@deepseek-ai/dsh-system-prompt'
import ToolRuntime from '@deepseek-ai/dsh-tools'

export type ScriptEntry =
  | StreamChunk[]
  | ((options: GenerateOptions) => StreamChunk[])
  | 'hang'
  | 'echo'

export class ScriptedAdapter extends LlmAdapter {
  readonly requests: GenerateOptions[] = []

  constructor(
    private script: ScriptEntry[],
    /** Used once the script is exhausted (keeps echo/hang adapters infinite). */
    private fallback: ScriptEntry | undefined = undefined,
  ) {
    super()
  }

  override resolveModel(
    provider: string,
    model: string,
  ): Promise<LlmResolvedModelInfo> {
    return Promise.resolve({ provider, id: model, name: model })
  }

  async *stream(options: GenerateOptions): AsyncIterable<StreamChunk> {
    this.requests.push(options)
    const entry = this.script.shift() ?? this.fallback
    if (entry === undefined) throw new Error('ScriptedAdapter: script exhausted')
    if (entry === 'hang') {
      yield { type: 'block-start', index: 0, blockType: 'text' }
      yield { type: 'text-delta', index: 0, text: 'partial' }
      await new Promise<void>((_resolve, reject) => {
        if (options.signal?.aborted) { reject(new Error('aborted')); return }
        options.signal?.addEventListener('abort', () => { reject(new Error('aborted')) }, { once: true })
      })
      return
    }
    const chunks = entry === 'echo' ? textResponse(lastUserText(options)) : (
      typeof entry === 'function' ? entry(options) : entry
    )
    for (const chunk of chunks) {
      if (options.signal?.aborted) throw new Error('aborted')
      yield chunk
    }
  }
}

/** One plain-text model response as a chunk stream. */
export function textResponse(text: string): StreamChunk[] {
  return [
    { type: 'block-start', index: 0, blockType: 'text' },
    ...Array.from(text, (char): StreamChunk => ({ type: 'text-delta', index: 0, text: char })),
    { type: 'block-end', index: 0, block: { type: 'text', text } },
    { type: 'usage', usage: { inputTokens: 10, outputTokens: Math.max(1, text.length) } },
    { type: 'finish', reason: { kind: 'stop' } },
  ]
}

/** Text of the last user message in a request (the echo source). */
function lastUserText(options: GenerateOptions): string {
  for (let index = options.messages.length - 1; index >= 0; index -= 1) {
    const message = options.messages[index]!
    if (message.role !== 'user') continue
    const parts: string[] = []
    for (const block of message.content) {
      if (block.type === 'text') parts.push(block.text)
    }
    if (parts.length > 0) return parts.join('')
  }
  return 'echo'
}

/** One declarative (config-created) agent entry for the AgentLoop config. */
export interface ConfigAgentEntry {
  readonly id: string
  readonly sessionId: string
  readonly provider: string
  readonly model: string
}

/** Boot the real harness with the scripted model route `mock`. */
export async function bootHarness(
  adapter: ScriptedAdapter,
  agents: readonly ConfigAgentEntry[] = [],
): Promise<Context> {
  const ctx = new Context()
  await ctx.plugin(LlmRuntime)
  await ctx.plugin(SessionStore)
  await ctx.plugin(SystemPrompt)
  await ctx.plugin(ToolRuntime)
  await ctx.plugin(AgentRegistry)
  await ctx.plugin(AgentLoop, { agents: agents as never })
  ctx.llm.registerAdapter(['mock'], adapter)
  return ctx
}

/** Create one real agent on the given scripted route (default: mock/echo). */
export function realAgent(ctx: Context, id: string, provider = 'mock') {
  return ctx.agentLoop.create(SessionId(id), { provider, model: 'mock' })
}
