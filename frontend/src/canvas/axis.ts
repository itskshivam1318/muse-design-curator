/**
 * Where explore axes sit on the canvas, as pure functions. An axis is the drawn form of an
 * exploration: a line from its source's right edge with one text card per top-level option
 * (branches live in the card's popover). Every axis of a source stacks downward, one row per
 * attribute, oldest first. Nothing here is stored: it is all computed from the source's bounds,
 * so axes move with their source.
 */
import type { Exploration, ExploreOption, Item, ItemAttribute, Point } from '../api'
import { optionTree } from '../explore/logic'
import type { Bounds } from './geometry'
import { itemBounds } from './nodeProps'

export const AXIS_GAP_X = 40
export const ROW_H = 132
export const CARD_W = 104
export const CARD_GAP = 9
/** From the source's top to the first line (room for the label above it). */
export const LINE_TOP = 20
/** From the line to the top of its cards. */
export const CARD_DROP = 8
export const CARD_H = 64
/** A kept card: the 84 px thumbnail and its "Name · kept" line. */
export const KEPT_CARD_H = 104
/** From the last card to the end handle. */
export const END_GAP = 24

export interface AxisCard {
  option_id: string
  x: number
  y: number
  w: number
  h: number
}

export interface AxisRow {
  exploration_id: string
  key: string
  label: string
  /** The line's y. */
  y: number
  x0: number
  /** The line's end, where the end handle sits. */
  x1: number
  cards: AxisCard[]
}

const byCreation = (a: Exploration, b: Exploration) => (a.created_at ?? '').localeCompare(b.created_at ?? '')

/** The options drawn as cards: non-dismissed and top-level (a branch whose parent was dismissed moves up). */
export const cardOptions = (e: Exploration): ExploreOption[] =>
  optionTree(e.options)
    .filter((r) => r.depth === 0)
    .map((r) => r.option)

/**
 * One row per exploration that has cards, stacked from `source.y` down in `created_at` order.
 * `explorations` are the source's own; `labels` maps attribute keys to labels (else the key).
 */
export function axisRows(
  source: Bounds,
  explorations: readonly Exploration[],
  labels: ReadonlyMap<string, string> = new Map(),
): AxisRow[] {
  const x0 = source.x + source.width + AXIS_GAP_X
  const rows: AxisRow[] = []
  for (const e of [...explorations].sort(byCreation)) {
    const options = cardOptions(e)
    if (options.length === 0) continue
    const y = source.y + LINE_TOP + rows.length * ROW_H
    const cards = options.map((o, i) => ({
      option_id: o.id,
      x: x0 + i * (CARD_W + CARD_GAP),
      y: y + CARD_DROP,
      w: CARD_W,
      h: o.kept_item_id ? KEPT_CARD_H : CARD_H,
    }))
    rows.push({
      exploration_id: e.id,
      key: e.key,
      label: labels.get(e.key) ?? e.key,
      y,
      x0,
      x1: x0 + options.length * CARD_W + (options.length - 1) * CARD_GAP + END_GAP,
      cards,
    })
  }
  return rows
}

/** The canvas area a row covers (label, line, cards, end handle), e.g. for fitting the view. */
export const rowBounds = (row: AxisRow): Bounds => ({
  x: row.x0,
  y: row.y - LINE_TOP,
  width: row.x1 - row.x0 + 10,
  height: LINE_TOP + CARD_DROP + Math.max(CARD_H, ...row.cards.map((c) => c.h)),
})

/** Where a kept take is placed: its card's spot on the axis (Keep's `at`). */
export function keptSlot(row: AxisRow, optionId: string): Point | undefined {
  const c = row.cards.find((card) => card.option_id === optionId)
  return c ? { x: c.x, y: c.y } : undefined
}

/** The top-level option whose card an option (or branch, at any depth) belongs to. */
export function cardOptionId(e: Exploration, optionId: string): string {
  const byId = new Map(e.options.map((o) => [o.id, o]))
  const onAxis = new Set(cardOptions(e).map((o) => o.id))
  let cur = byId.get(optionId)
  const seen = new Set<string>()
  while (cur && !onAxis.has(cur.id) && cur.parent_option_id && !seen.has(cur.id)) {
    seen.add(cur.id)
    cur = byId.get(cur.parent_option_id)
  }
  return cur?.id ?? optionId
}

/** An option's kept take when it is a live item on the board (a deleted one leaves a stale id). */
function keptItem(o: ExploreOption, items: ReadonlyMap<string, Item>): Item | null {
  if (!o.kept_item_id || o.status === 'dismissed') return null
  const item = items.get(o.kept_item_id)
  return item && !item.staged ? item : null
}

/**
 * What a card shows as kept: its own kept take, else the first kept take among its branches.
 * `items` are the board's visible items.
 */
export function keptOnCard(
  e: Exploration,
  cardId: string,
  items: ReadonlyMap<string, Item>,
): { option: ExploreOption; item: Item } | null {
  const rows = optionTree(e.options)
  const start = rows.findIndex((r) => r.option.id === cardId)
  if (start === -1) return null
  for (let i = start; i < rows.length && (i === start || rows[i].depth > 0); i++) {
    const item = keptItem(rows[i].option, items)
    if (item) return { option: rows[i].option, item }
  }
  return null
}

export interface DrawnAxis {
  source: Item
  rows: AxisRow[]
  explorations: Exploration[]
}

/**
 * Every axis to draw over `items` (the canvas's visible items, as positioned), and the kept items
 * the cards show instead of drawing them loose. A source must be on the canvas: a staged or
 * removed source, or a kept take that a card already shows, draws no axis.
 */
export function drawnAxes(
  items: readonly Item[],
  explorations: readonly Exploration[],
  labels?: ReadonlyMap<string, string>,
): { axes: DrawnAxis[]; hidden: Set<string> } {
  const byId = new Map(items.filter((i) => !i.staged).map((i) => [i.id, i]))
  const bySource = new Map<string, Exploration[]>()
  for (const e of explorations) bySource.set(e.item_id, [...(bySource.get(e.item_id) ?? []), e])
  // kept item id → the source whose card would show it
  const shownBy = new Map<string, string>()
  for (const [sourceId, list] of bySource) {
    if (!byId.has(sourceId)) continue
    for (const e of list)
      for (const o of cardOptions(e)) {
        const k = keptOnCard(e, o.id, byId)
        if (k && k.item.id !== sourceId) shownBy.set(k.item.id, sourceId)
      }
  }
  // a source is drawn when it is on the canvas and no drawn axis shows it as a card (takes form no cycles)
  const memo = new Map<string, boolean>()
  const isDrawn = (id: string, depth = 0): boolean => {
    const known = memo.get(id)
    if (known !== undefined) return known
    let drawn = byId.has(id)
    const by = shownBy.get(id)
    if (drawn && by !== undefined && depth < 64) drawn = !isDrawn(by, depth + 1)
    memo.set(id, drawn)
    return drawn
  }
  const hidden = new Set<string>()
  for (const [keptId, sourceId] of shownBy) if (byId.has(keptId) && isDrawn(sourceId)) hidden.add(keptId)
  const axes: DrawnAxis[] = []
  for (const item of items) {
    const list = bySource.get(item.id)
    if (!list || !isDrawn(item.id)) continue
    const rows = axisRows(itemBounds(item), list, labels)
    if (rows.length) axes.push({ source: item, rows, explorations: list })
  }
  return { axes, hidden }
}

/** The kept items shown on the axes of `sourceIds`: they move with their source. */
export function keptFollowers(axes: readonly DrawnAxis[], sourceIds: ReadonlySet<string>, items: ReadonlyMap<string, Item>): string[] {
  const out: string[] = []
  for (const a of axes) {
    if (!sourceIds.has(a.source.id)) continue
    for (const e of a.explorations)
      for (const o of cardOptions(e)) {
        const k = keptOnCard(e, o.id, items)
        if (k && !sourceIds.has(k.item.id)) out.push(k.item.id)
      }
  }
  return out
}

// ---- the focused axis: the one a chip or the picker just chose (drawn in the accent) ----
type Listener = () => void
let focused: string | null = null
const listeners = new Set<Listener>()
export const focusStore = {
  get: () => focused,
  set(id: string | null) {
    if (id === focused) return
    focused = id
    listeners.forEach((l) => l())
  },
  subscribe(l: Listener) {
    listeners.add(l)
    return () => {
      listeners.delete(l)
    }
  },
}
export const focusAxis = (explorationId: string | null): void => focusStore.set(explorationId)

/** Where a value came from, as the chip's mark shows it (the `sources` of the Chips artboard). */
export type ChipSource = 'measured' | 'read' | 'estimated' | 'web' | 'you' | 'unknown'

export function chipSource(a: ItemAttribute): ChipSource {
  if (a.value === null || a.status === 'missing') return 'unknown'
  if (a.source === 'user' || a.status === 'edited' || a.status === 'confirmed') return 'you'
  if (a.measured) return 'measured'
  if (a.source === 'web' || a.source === 'live') return 'web'
  if (a.status === 'uncertain') return 'estimated'
  return 'read'
}
