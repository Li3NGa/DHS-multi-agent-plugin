import { createUserMessage } from '@deepseek-ai/dsh-llm'
import type { Agent } from '@deepseek-ai/dsh-agent'

export interface Task {
  prompt: string
  agent: string
}

export interface AgentResult {
  agent: string
  content: string
}

function messageText(value: unknown): string {
  if (!value || typeof value !== 'object') return ''
  const message = value as { content?: unknown }
  if (!Array.isArray(message.content)) return ''
  return message.content
    .map((part) => {
      if (!part || typeof part !== 'object') return ''
      const item = part as { type?: unknown; text?: unknown }
      return item.type === 'text' && typeof item.text === 'string' ? item.text : ''
    })
    .join('')
}

export class AgentRunner {
  async run(task: Task, agent: Agent): Promise<AgentResult> {
    const before = agent.session.events.length

    agent.followup(createUserMessage({
      content: [{ type: 'text', text: task.prompt }],
      source: { kind: 'user' },
    }))

    await agent.whenIdle()

    const events = agent.session.events.slice(before)
    const assistant = [...events].reverse().find((event) => event.type === 'assistant/message')
    if (!assistant || assistant.type !== 'assistant/message') {
      throw new Error(`agent "${task.agent}" completed without an assistant result`)
    }

    return {
      agent: task.agent,
      content: messageText(assistant.data.message),
    }
  }
}
