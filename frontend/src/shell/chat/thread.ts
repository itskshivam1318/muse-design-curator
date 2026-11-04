/** Pure helpers for the chat thread in the agent card. */
import type { AgentAnswer, AgentMessage, AgentStep } from '../../api'

/** One line of the thread: something said, or a tool call the agent made between messages. */
export type Entry = { kind: 'message'; message: AgentMessage } | { kind: 'step'; step: AgentStep }

const at = (e: Entry) => Date.parse(e.kind === 'message' ? e.message.created_at : e.step.created_at)

/** Messages and steps in one list by `created_at`; at the same moment a message comes first. */
export function threadEntries(messages: AgentMessage[], steps: AgentStep[]): Entry[] {
  const entries: Entry[] = [
    ...messages.map((message): Entry => ({ kind: 'message', message })),
    ...steps.map((step): Entry => ({ kind: 'step', step })),
  ]
  // Array.prototype.sort is stable: equal times keep messages before steps
  return entries.sort((a, b) => at(a) - at(b))
}

export type TextPart = { text: string } | { itemId: string }

const ITEM_ID = /\bitm_[A-Za-z0-9]+/g

/** The text cut into plain runs and the item ids (`itm_…`) in it. */
export function textParts(text: string): TextPart[] {
  const parts: TextPart[] = []
  let from = 0
  for (const m of text.matchAll(ITEM_ID)) {
    if (m.index > from) parts.push({ text: text.slice(from, m.index) })
    parts.push({ itemId: m[0] })
    from = m.index + m[0].length
  }
  if (from < text.length) parts.push({ text: text.slice(from) })
  return parts
}

/** The person's answer as the short line their chat shows. */
export function answerLine(answer: AgentAnswer): string {
  if (answer.choice !== undefined) return answer.choice
  if (answer.box) return 'Fixed with a box'
  if (answer.text?.trim().toLowerCase() === 'yes') return 'Yes'
  return answer.text ?? ''
}
