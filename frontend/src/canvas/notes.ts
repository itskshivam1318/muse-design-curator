/**
 * Where explore option notes sit on the canvas and the lines that join them, as pure functions.
 * The notes are the same list as the drawer: optionTree decides which options exist (no
 * dismissed ones; a branch whose parent was dismissed joins the source instead).
 */
import type { Exploration, ExploreOption, Item, Point } from '../api'
import { optionTree } from '../explore/logic'
import type { Bounds } from './geometry'
import { itemBounds, lineagePoints } from './nodeProps'

export const NOTE_W = 220
export const NOTE_H = 96
const OFFSET_X = 60 // from the source's right edge to the first column
const GAP_Y = 16
const PER_COLUMN = 6
const COLUMN_STEP = 240

/**
 * Slots `start` … `start + count - 1` of a source's fan: columns of 6 to the right of the
 * source, each centred vertically on it. A column is centred on all the slots it holds up to
 * `start + count`, so a later batch (start > 0) continues the same columns.
 */
export function fanPositions(source: Bounds, count: number, start: number): Point[] {
  const total = start + count
  const cy = source.y + source.height / 2
  const out: Point[] = []
  for (let i = start; i < total; i++) {
    const col = Math.floor(i / PER_COLUMN)
    const row = i % PER_COLUMN
    const inColumn = Math.min(PER_COLUMN, total - col * PER_COLUMN)
    const top = cy - (inColumn * NOTE_H + (inColumn - 1) * GAP_Y) / 2
    out.push({ x: source.x + source.width + OFFSET_X + col * COLUMN_STEP, y: top + row * (NOTE_H + GAP_Y) })
  }
  return out
}

/** A note's spot: where it was dropped, otherwise slot `index` of a fan of `total` notes. */
export function notePlacement(option: ExploreOption, index: number, source: Bounds, total = index + 1): Point {
  if (option.x !== null && option.y !== null) return { x: option.x, y: option.y }
  return fanPositions(source, total - index, index)[0]
}

export interface PlacedNote {
  option: ExploreOption
  exploration: Exploration
  /** The parent note when it is shown; null joins the source. */
  parentId: string | null
  x: number
  y: number
}

/**
 * Every visible note, placed. One fan per source item holds all its explorations' options
 * (oldest exploration first, each in drawer order). Notes whose source is gone are left out.
 */
export function placedNotes(explorations: readonly Exploration[], items: readonly Item[]): PlacedNote[] {
  const byId = new Map(items.map((i) => [i.id, i]))
  const bySource = new Map<string, Exploration[]>()
  for (const e of explorations) {
    if (byId.has(e.item_id)) bySource.set(e.item_id, [...(bySource.get(e.item_id) ?? []), e])
  }
  const out: PlacedNote[] = []
  for (const [itemId, list] of bySource) {
    const source = itemBounds(byId.get(itemId)!)
    const sorted = [...list].sort((a, b) => (a.created_at ?? '').localeCompare(b.created_at ?? ''))
    const rows = sorted.flatMap((exploration) =>
      optionTree(exploration.options).map(({ option, depth }) => ({ option, depth, exploration })),
    )
    rows.forEach(({ option, depth, exploration }, i) => {
      out.push({
        option,
        exploration,
        parentId: depth > 0 ? option.parent_option_id : null,
        ...notePlacement(option, i, source, rows.length),
      })
    })
  }
  return out
}

export const noteBounds = (n: Point): Bounds => ({ x: n.x, y: n.y, width: NOTE_W, height: NOTE_H })

/**
 * Lines for the notes, always shown: source → note (parent note → note for a branch), and
 * note → each image generated from it.
 */
export function noteLines(
  explorations: readonly Exploration[],
  items: readonly Item[],
): Array<{ id: string; points: number[] }> {
  const notes = placedNotes(explorations, items)
  const byOption = new Map(notes.map((n) => [n.option.id, n]))
  const byItem = new Map(items.map((i) => [i.id, i]))
  const lines = notes.map((n) => {
    const parent = n.parentId ? byOption.get(n.parentId) : undefined
    const from = parent ? noteBounds(parent) : itemBounds(byItem.get(n.exploration.item_id)!)
    return { id: `note-${n.option.id}`, points: lineagePoints(from, noteBounds(n)) }
  })
  for (const item of items) {
    const note = item.explore_option_id ? byOption.get(item.explore_option_id) : undefined
    if (note) lines.push({ id: `gen-${item.id}`, points: lineagePoints(noteBounds(note), itemBounds(item)) })
  }
  return lines
}
