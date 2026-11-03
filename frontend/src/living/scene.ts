/**
 * The living board's scene: board data (items, explorations, analyses, the selection) turned into
 * physics bodies with homes, and the edges drawn between them. Pure; the runtime syncs its world to it.
 */
import type { AnalysisView, Exploration, ExploreOption, Item, Point } from '../api'
import type { Bounds } from '../canvas/geometry'
import { itemBounds } from '../canvas/nodeProps'
import { optionTree } from '../explore/logic'
import { calloutSize, cardOf, WHOLE } from '../map/cards'
import { partAnchor } from '../map/regions'
import { isKept } from '../map/results'
import { type BodySpec, FEEL, type Home } from './physics'
import { CALLOUT_GAP, ellipsePoint, HUB_GAP, HUB_H, HUB_W, KEPT_EXTRA, PETAL, petalAngles, petalRadius, ringAngles } from './ring'

const BADGE_W = 120
const BADGE_H = 28
/** A collapsed flower's docked takes sit this far from its badge. */
const BADGE_KEPT_R = 70

export interface FlowerModel {
  /** The exploration's id. */
  id: string
  /** Its hub's body id (also its badge's, while collapsed). */
  hubId: string
  /** The body it grows from: a board item, or a docked take. */
  sourceId: string
  key: string
  label: string
  /** The label of the part a physical dimension lives on; null for a whole-item one. */
  part: string | null
  /** Every option not dismissed, in petal order (kept ones keep their slot). */
  options: ExploreOption[]
  collapsed: boolean
}

/** An edge's end on a body; with no anchor, the point where the body's edge faces the other end. */
export type EdgeEnd = { body: string; anchor?: { fx: number; fy: number } }

export interface Edge {
  id: string
  kind: 'stem' | 'leader' | 'spoke'
  from: EdgeEnd
  to: EdgeEnd
  kept?: boolean
}

export interface Scene {
  specs: BodySpec[]
  edges: Edge[]
  flowers: FlowerModel[]
  /** Each docked take's item id → the option it was kept from and the hub it rings. */
  docked: Map<string, { optionId: string; hubId: string }>
  /**
   * Each kept take on the board (docked or not) → its slot in its flower's ring (`home`, rel to the
   * hub; `index` is its option's place in the flower's options) and how near (`reach`, the radius of
   * the ring it shows) a drop must land to dock there.
   */
  slots: Map<string, { optionId: string; hubId: string; index: number; home: Home; reach: number }>
}

export interface SceneInput {
  items: readonly Item[]
  explorations: readonly Exploration[]
  /**
   * Each item's analysis: null when it failed (no callouts, hubs open downward); undefined while
   * loading (no callouts; its flowers without a stored offset wait).
   */
  analyses: ReadonlyMap<string, AnalysisView | null | undefined>
  labels: ReadonlyMap<string, string>
  collapsed: (explorationId: string) => boolean
  selectedId: string | null
  /** The open add-forms on a card of the selected item (they make it taller). */
  formsOn?: (card: string) => number
  /** The selected item's callout cards as drawn (canvas units): their measured height wins over the estimate. */
  calloutHeights?: ReadonlyMap<string, number>
  /**
   * The selection toolbar's size (canvas units, including its gap to the item): it floats centred
   * just above the selected item, and nothing may sit under it.
   */
  toolbar?: { w: number; h: number }
}

interface Card {
  /** The card's slot angle around its item. */
  angle: number
  /** Where its part sits on the item (canvas units); null for the Whole item card. */
  anchor: Point | null
}

const centre = (b: Bounds): Point => ({ x: b.x + b.width / 2, y: b.y + b.height / 2 })

/** An item's cards (its parts', then Whole item) with their ring slots, as the callouts draw them. */
function cardsOf(item: Item, analysis: AnalysisView): Map<string, Card> {
  const b = itemBounds(item)
  const c = centre(b)
  const anchors = [...analysis.parts.map((p) => partAnchor(b, p, item.note_text)), null]
  const angles = ringAngles(
    { w: b.width, h: b.height },
    anchors.map((p) => (p ? { x: p.x - c.x, y: p.y - c.y } : null)),
  )
  const keys = [...analysis.parts.map((p) => p.key), WHOLE]
  return new Map(keys.map((k, i) => [k, { angle: angles[i], anchor: anchors[i] }]))
}

const calloutId = (itemId: string, card: string) => `callout:${itemId}:${card}`
const rel = (to: string, p: Point): Home => ({ kind: 'rel', to, dx: p.x, dy: p.y })
const polar = (angle: number, r: number): Point => ({ x: Math.cos(angle) * r, y: Math.sin(angle) * r })

/** How far from its hub a kept take docks: past the petals, or close round a collapsed flower's badge. */
const keptRadius = (m: FlowerModel) => (m.collapsed ? BADGE_KEPT_R : petalRadius(m.options.length) + KEPT_EXTRA)

/**
 * Where the take of the flower's option `index` docks, relative to its hub, for a hub `offset` from
 * its source: the ring opens along the offset, so it turns as the hub moves round its source.
 */
export function keptSlot(m: FlowerModel, index: number, offset: Point): Point {
  return polar(petalAngles(Math.atan2(offset.y, offset.x), m.options.length)[index], keptRadius(m))
}

/** Where that take docks on the board for the hub and its source where they are now (live centres). */
export function dockedCentre(m: FlowerModel, index: number, hub: Point, source: Point): Point {
  const p = keptSlot(m, index, { x: hub.x - source.x, y: hub.y - source.y })
  return { x: hub.x + p.x, y: hub.y + p.y }
}

export function buildScene(input: SceneInput): Scene {
  const { items, explorations, analyses, labels, collapsed, selectedId, formsOn = () => 0, calloutHeights, toolbar } = input
  const onBoard = items.filter((i) => !i.staged) // staged takes wait in their option's stage
  const byId = new Map(onBoard.map((i) => [i.id, i]))
  const cardCache = new Map<string, Map<string, Card> | null>()
  const cards = (item: Item) => {
    if (!cardCache.has(item.id)) {
      const a = analyses.get(item.id)
      cardCache.set(item.id, a ? cardsOf(item, a) : null)
    }
    return cardCache.get(item.id)!
  }

  // each flower's geometry first: docked takes (listed among the items) need their hub's direction.
  // A flower whose source analysis is still loading and that has no stored offset waits (no hub, no
  // petals, its docked takes are ordinary items until then): it would otherwise home at a guess.
  const stored = (e: Exploration) => e.dx != null && e.dy != null
  const flowers = [...explorations]
    .filter((e) => byId.has(e.item_id) && (stored(e) || analyses.get(e.item_id) !== undefined))
    .sort((x, y) => (x.id < y.id ? -1 : x.id > y.id ? 1 : 0))
    .map((e) => {
      const source = byId.get(e.item_id)!
      const analysis = analyses.get(source.id) ?? null
      const card = analysis ? (cardOf(analysis, e.key) ?? WHOLE) : null
      const slot = card ? cards(source)!.get(card)! : null
      const b = itemBounds(source)
      const offset: Point =
        stored(e)
          ? { x: e.dx!, y: e.dy! }
          : ellipsePoint({ w: b.width, h: b.height }, slot?.angle ?? Math.PI / 2, HUB_GAP)
      const options = optionTree(e.options).map((r) => r.option)
      const dim = analysis?.dimensions.find((d) => d.key === e.key)
      const model: FlowerModel = {
        id: e.id,
        hubId: `hub:${e.id}`,
        sourceId: source.id,
        key: e.key,
        label: dim?.label ?? labels.get(e.key) ?? e.key,
        part: dim?.type === 'physical' ? (analysis?.parts.find((p) => p.key === dim.part)?.label ?? null) : null,
        options,
        collapsed: collapsed(e.id),
      }
      const anchor = slot?.anchor ?? null
      const fraction = anchor ? { fx: (anchor.x - b.x) / b.width, fy: (anchor.y - b.y) / b.height } : undefined
      const angles = petalAngles(Math.atan2(offset.y, offset.x), options.length)
      return { model, source, card, offset, start: anchor ?? centre(b), fraction, angles }
    })

  // a kept take is docked in its ring unless it was dragged out (or is not on the board)
  const docked = new Map<string, { optionId: string; hubId: string }>()
  const dockHome = new Map<string, Home>()
  const slots: Scene['slots'] = new Map()
  for (const f of flowers) {
    const reach = f.model.collapsed ? BADGE_KEPT_R : petalRadius(f.model.options.length)
    f.model.options.forEach((o, i) => {
      if (!isKept(o) || !byId.has(o.kept_item_id!)) return
      const home = rel(f.model.hubId, keptSlot(f.model, i, f.offset))
      slots.set(o.kept_item_id!, { optionId: o.id, hubId: f.model.hubId, index: i, home, reach })
      if (o.undocked) return
      docked.set(o.kept_item_id!, { optionId: o.id, hubId: f.model.hubId })
      dockHome.set(o.kept_item_id!, home)
    })
  }

  const specs: BodySpec[] = []
  const edges: Edge[] = []
  for (const i of onBoard) {
    const home = dockHome.get(i.id)
    if (home) specs.push({ id: i.id, kind: 'kept', w: i.w, h: i.h, home })
    else {
      const c = centre(itemBounds(i))
      specs.push({ id: i.id, kind: 'item', w: i.w, h: i.h, home: { kind: 'abs', x: c.x, y: c.y } })
    }
  }

  const selected = selectedId ? byId.get(selectedId) : undefined
  const selectedCards = selected ? cards(selected) : null

  for (const f of flowers) {
    const { model, source, offset, start } = f
    const hubId = model.hubId
    const sourceEnd: EdgeEnd = f.fraction ? { body: source.id, anchor: f.fraction } : { body: source.id }
    if (selectedCards && source.id === selectedId && f.card) {
      const callout = calloutId(source.id, f.card)
      edges.push({ id: `leader:${model.id}`, kind: 'leader', from: sourceEnd, to: { body: callout } })
      edges.push({ id: `stem:${model.id}`, kind: 'stem', from: { body: callout }, to: { body: hubId } })
    } else {
      edges.push({ id: `stem:${model.id}`, kind: 'stem', from: sourceEnd, to: { body: hubId } })
    }

    if (model.collapsed) {
      specs.push({ id: hubId, kind: 'badge', w: BADGE_W, h: BADGE_H, home: rel(source.id, offset), start, delay: 0 })
    } else {
      specs.push({ id: hubId, kind: 'hub', w: HUB_W, h: HUB_H, home: rel(source.id, offset), start, delay: 0 })
    }
    const R = petalRadius(model.options.length)
    let shown = 0 // petals grow in one after another; kept options keep their slot but no turn
    model.options.forEach((o, i) => {
      if (isKept(o)) {
        if (docked.get(o.kept_item_id!)?.hubId === hubId) {
          edges.push({ id: `spoke:${o.id}`, kind: 'spoke', from: { body: hubId }, to: { body: o.kept_item_id! }, kept: true })
        }
        return
      }
      if (model.collapsed) return
      const id = `petal:${o.id}`
      specs.push({ id, kind: 'petal', w: PETAL, h: PETAL, home: rel(hubId, polar(f.angles[i], R)), delay: FEEL.hubLeadMs + shown++ * FEEL.petalStaggerMs })
      edges.push({ id: `spoke:${o.id}`, kind: 'spoke', from: { body: hubId }, to: { body: id } })
    })
  }

  if (selected && selectedCards) {
    const analysis = analyses.get(selected.id)!
    const b = itemBounds(selected)
    let n = 0
    for (const [card, { angle }] of selectedCards) {
      const p = ellipsePoint({ w: b.width, h: b.height }, angle, CALLOUT_GAP)
      const size = calloutSize(selected, analysis, card, formsOn(card))
      const h = calloutHeights?.get(card) ?? size.h
      specs.push({ id: calloutId(selected.id, card), kind: 'callout', w: size.w, h, home: rel(selected.id, p), ignore: selected.id, delay: n++ * FEEL.calloutStaggerMs })
    }
  }
  if (selected && toolbar) {
    const b = itemBounds(selected)
    const home = rel(selected.id, { x: 0, y: -(b.height / 2 + toolbar.h / 2) })
    specs.push({ id: `toolbar:${selected.id}`, kind: 'obstacle', w: toolbar.w, h: toolbar.h, home, ignore: selected.id })
  }

  return { specs, edges, flowers: flowers.map((f) => f.model), docked, slots }
}
