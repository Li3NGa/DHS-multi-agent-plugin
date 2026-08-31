/**
 * Native Planner V1 — Phase E3.
 *
 * Turns raw user input into a strategy-agnostic PlannerPlan.
 *
 * Parsing precedence (ported from the Python reference `parse_plan`, not its
 * internals):
 *   1. structured JSON — fenced code blocks, then the first '{'..last '}'
 *      span, then the whole text; accepts either `{ "tasks": [...] }` or a
 *      bare `[...]`; each entry needs a prompt/description/task field
 *   2. one-task-per-line fallback — strips bullets/numbering; an empty text
 *      falls back to a single task carrying the original prompt
 *
 * The Planner NEVER calls a model itself: raw plan text comes from an
 * injected `PlanSource` hook (tests script it; production wraps a real model
 * call). The Planner does not validate, repair or route — that is the
 * Validator's / Router's job, so each stage stays independently testable.
 */
import { PlanParseError } from './errors'
import type { PlanFormat, PlannerPlan, PlannerResult, PlanSource, PlanTask } from './types'

const PLACEHOLDER_DEPENDENCY = '前置任务的 id，没有依赖则为空数组'
const FENCE_RE = /```(?:json)?\s*([\s\S]*?)```/g

/** JSON candidate substrings, most-constrained first. */
function jsonCandidates(text: string): string[] {
  const candidates: string[] = []
  for (const match of text.matchAll(FENCE_RE)) {
    candidates.push(match[1]!.trim())
  }
  const first = text.indexOf('{')
  const last = text.lastIndexOf('}')
  if (first !== -1 && last > first) {
    candidates.push(text.slice(first, last + 1))
  }
  candidates.push(text.trim())
  return candidates
}

type RawTask = Record<string, unknown>

function parseJsonTasks(text: string): RawTask[] | undefined {
  for (const candidate of jsonCandidates(text)) {
    let data: unknown
    try {
      data = JSON.parse(candidate)
    } catch {
      continue
    }
    if (Array.isArray(data)) {
      const dicts = data.filter((entry): entry is RawTask => typeof entry === 'object' && entry !== null && !Array.isArray(entry))
      if (dicts.length > 0) return dicts
      return undefined
    }
    if (typeof data === 'object' && data !== null) {
      const tasks = (data as { tasks?: unknown }).tasks
      if (Array.isArray(tasks)) {
        const dicts = tasks.filter((entry): entry is RawTask => typeof entry === 'object' && entry !== null && !Array.isArray(entry))
        if (dicts.length > 0) return dicts
      }
      // a JSON object without a usable tasks array is not a plan
      return undefined
    }
  }
  return undefined
}

function tasksFromJson(raw: readonly RawTask[]): PlanTask[] {
  const tasks: PlanTask[] = []
  raw.forEach((entry, index) => {
    const prompt = String(entry.prompt ?? entry.description ?? entry.task ?? '').trim()
    if (prompt.length === 0) return
    const id = String(entry.id ?? `task_${index + 1}`).trim() || `task_${index + 1}`
    const dependsOn = Array.isArray(entry.dependsOn ?? entry.depends_on)
      ? ((entry.dependsOn ?? entry.depends_on) as unknown[])
          .map((dep) => String(dep).trim())
          .filter((dep) => dep.length > 0 && dep !== PLACEHOLDER_DEPENDENCY)
      : undefined
    // the requested agent is kept verbatim so validation can detect an
    // UNKNOWN agent; concrete routing happens later (Router), after the plan
    // has been validated / repaired. Duplicate ids are NOT renamed — they
    // must fail validation loudly.
    const agentId = entry.agent !== undefined && String(entry.agent).trim().length > 0
      ? String(entry.agent).trim()
      : undefined
    const capsRaw = entry.requiredCapabilities ?? entry.required_capabilities
    const requiredCapabilities = Array.isArray(capsRaw)
      ? [...new Set(capsRaw.map((cap) => String(cap).trim()).filter((cap) => cap.length > 0))].sort()
      : undefined
    tasks.push({
      id,
      prompt,
      ...(agentId !== undefined ? { agentId } : {}),
      ...(dependsOn !== undefined && dependsOn.length > 0 ? { dependsOn } : {}),
      ...(requiredCapabilities !== undefined && requiredCapabilities.length > 0
        ? { requiredCapabilities }
        : {}),
    })
  })
  return tasks
}

function tasksFromLines(text: string, prompt: string): PlanTask[] {
  const lines = text
    .split(/\r?\n/)
    .map((line) => line.trim().replace(/^[-*0-9.\s]+/, '').trim())
    .filter((line) => line.length > 0)
  if (lines.length === 0) {
    return [{ id: 'task_1', prompt: String(prompt) }]
  }
  return lines.map((line, index) => ({ id: `task_${index + 1}`, prompt: line }))
}

/**
 * Parse raw plan text into a PlannerPlan. `prompt` is the original user
 * input, used as the fallback single-task prompt when the text carries no
 * usable tasks.
 */
export function parsePlanText(text: string, prompt: string): { plan: PlannerPlan; format: PlanFormat } {
  const raw = parseJsonTasks(text)
  if (raw !== undefined) {
    const tasks = tasksFromJson(raw)
    if (tasks.length > 0) return { plan: { tasks }, format: 'json' }
  }
  return { plan: { tasks: tasksFromLines(text, prompt) }, format: 'lines' }
}

export interface PlannerDeps {
  /** Injectable raw-plan-text source (model call in production). */
  readonly source: PlanSource
}

export class PlannerV1 {
  readonly #source: PlanSource

  constructor(deps: PlannerDeps) {
    this.#source = deps.source
  }

  /** Plan one user input into a (parsed, not yet validated) PlannerPlan. */
  async plan(input: string): Promise<PlannerResult> {
    const text = await this.#source(input)
    if (typeof text !== 'string') {
      throw new PlanParseError('plan source returned no text')
    }
    const { plan, format } = parsePlanText(text, input)
    return { plan, format, notes: [] }
  }
}

/** Convenience factory. */
export function createPlanner(deps: PlannerDeps): PlannerV1 {
  return new PlannerV1(deps)
}
