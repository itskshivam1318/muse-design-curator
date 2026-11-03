/** Pure helpers for showing an agent run in the agent card. */
import type { AgentRun, AgentRunStatus, AgentRunWithSteps, AgentStep } from '../api'

/** The step list with `incoming` in it: a known id is replaced in place, the rest stay in turn order. */
export function mergeSteps(prev: AgentStep[], incoming: AgentStep): AgentStep[] {
  const at = prev.findIndex((s) => s.id === incoming.id)
  if (at !== -1) {
    const next = prev.slice()
    next[at] = incoming
    return next
  }
  return [...prev, incoming].sort((a, b) => a.turn - b.turn)
}

/**
 * A freshly fetched run, keeping any cached step it does not have yet (one that arrived as an event
 * while the fetch was in flight). For a step in both, the fetched copy wins.
 */
export function mergeFetched(fresh: AgentRunWithSteps, held: AgentRunWithSteps | undefined): AgentRunWithSteps {
  if (!held) return fresh
  const known = new Set(fresh.steps.map((s) => s.id))
  const extra = held.steps.filter((s) => !known.has(s.id))
  return extra.length ? { ...fresh, steps: extra.reduce(mergeSteps, fresh.steps) } : fresh
}

/** Each deliverable, done once the output has a section for it with at least one item. */
export function deliverableStatus(run: AgentRun): { name: string; done: boolean }[] {
  const sections = run.output?.sections ?? []
  return run.deliverables.map((name) => ({
    name,
    done: sections.some((s) => s.deliverable === name && s.items.length > 0),
  }))
}

const ARGS_MAX = 60
/** Shown on their own (the step's line and star), not in the call. */
const HIDDEN_ARGS = new Set(['say', 'highlight'])

/** The step's call as one short line: `tool(arg=value, …)`, args cut to 60 characters. */
export function toolCall(step: AgentStep): string {
  const args = Object.entries(step.args ?? {})
    .filter(([k]) => !HIDDEN_ARGS.has(k))
    .map(([k, v]) => `${k}=${JSON.stringify(v)}`)
    .join(', ')
  return `${step.tool}(${args.length > ARGS_MAX ? `${args.slice(0, ARGS_MAX)}…` : args})`
}

export const STATUS_TEXT: Record<AgentRunStatus, string> = {
  running: 'working',
  needs_input: 'needs you',
  done: 'done',
  paused: 'paused',
}

export const agentName = (run: AgentRun): string => (run.source === 'mcp' ? 'Claude Code' : 'Muse')
