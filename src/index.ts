import { Service, type Context } from '@deepseek-ai/cordis'
import type { Agent } from '@deepseek-ai/dsh-agent'
import { AgentRunner, type AgentResult, type Task } from './runner.js'

declare module '@deepseek-ai/cordis' {
  interface Context {
    multiAgent: MultiAgentService
  }
}

export type MultiAgentStrategy = 'broadcast'

export interface MultiAgentRunOptions {
  strategy: MultiAgentStrategy
  agents: string[]
  prompt: string
}

export interface MultiAgentRunResult {
  strategy: MultiAgentStrategy
  results: AgentResult[]
}

export class MultiAgentService extends Service {
  static inject = ['agents']

  private readonly runner = new AgentRunner()
  private readonly context: Context

  constructor(ctx: Context) {
    super(ctx, 'multiAgent')
    this.context = ctx
  }

  async run(options: MultiAgentRunOptions): Promise<MultiAgentRunResult> {
    if (options.strategy !== 'broadcast') {
      throw new Error(`unsupported strategy "${options.strategy}"`)
    }
    if (options.agents.length === 0) {
      throw new Error('broadcast requires at least one agent')
    }

    const tasks: Task[] = options.agents.map((agent) => ({
      agent,
      prompt: options.prompt,
    }))

    const results = await Promise.all(tasks.map(async (task) => {
      const agent = this.context.agents.get(task.agent as Agent['id'])
      if (!agent) {
        throw new Error(`agent "${task.agent}" not found`)
      }
      return this.runner.run(task, agent)
    }))

    return { strategy: 'broadcast', results }
  }
}

export const name = 'dhs-multi-agent'

export function apply(ctx: Context) {
  ctx.plugin(MultiAgentService)
}
