/**
 * Exploring a note writes its options out in full at once: no flower, no petals. Each take waits on
 * the board as a pending note (still staged on the server) until it is kept or removed.
 */
import type { Exploration, ExploreOption, Item } from '../api'

export interface PendingNote {
  option: ExploreOption
  exploration: Exploration
}

/** Explorations grown from a note: they show as pending notes, never as a flower. */
export function isNoteExploration(e: Exploration, byId: ReadonlyMap<string, Item>): boolean {
  return byId.get(e.item_id)?.kind === 'note'
}

/**
 * Each pending note's item id → its option and exploration: a staged note take of a note's option
 * that is neither dismissed nor kept (a kept take is an ordinary note).
 */
export function pendingNotes(items: readonly Item[], explorations: readonly Exploration[]): Map<string, PendingNote> {
  const byId = new Map(items.map((i) => [i.id, i]))
  const out = new Map<string, PendingNote>()
  for (const exploration of explorations) {
    if (!isNoteExploration(exploration, byId)) continue
    for (const option of exploration.options) {
      if (option.status === 'dismissed' || option.kept_item_id) continue
      for (const id of option.takes) {
        const take = byId.get(id)
        if (take && take.staged && take.kind === 'note') out.set(id, { option, exploration })
      }
    }
  }
  return out
}

/** Each note → how many of its versions are still being written. */
export function notesBeingWritten(items: readonly Item[], explorations: readonly Exploration[]): Map<string, number> {
  const byId = new Map(items.map((i) => [i.id, i]))
  const out = new Map<string, number>()
  for (const e of explorations) {
    if (!isNoteExploration(e, byId)) continue
    const n = e.options.filter((o) => o.status === 'visualizing').length
    if (n) out.set(e.item_id, (out.get(e.item_id) ?? 0) + n)
  }
  return out
}

/** The passage a pending note changed, or null when the whole text was rewritten (nothing to mark). */
export function changedPassage(item: Item): [number, number] | null {
  const range = item.generation?.changed_range
  const len = item.note_text?.length ?? 0
  if (!range || range.length !== 2) return null
  const [a, b] = range
  return a <= 0 && b >= len ? null : [a, b]
}
