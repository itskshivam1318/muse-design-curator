/**
 * The board's exploration map: one flower per exploration whose source item is on the board, each
 * starting at its dimension's callout card (computed even while the callouts are not shown, so a
 * flower stays put whether its item is selected or not), laid out into free space by `layoutFlowers`.
 */
import { useQueries } from '@tanstack/react-query'
import { useMemo, useSyncExternalStore } from 'react'
import { type AnalysisView, type Exploration, type ExploreOption, getAnalysis, type Item, keys, type Point } from '../api'
import type { Bounds } from '../canvas/geometry'
import { itemBounds } from '../canvas/nodeProps'
import { useDemo } from '../demo'
import { optionTree } from '../explore/logic'
import { useBoardLens, useExplorations } from '../queries'
import { calloutBounds, cardOf, WHOLE } from './cards'
import { collapsedVersion, isCollapsed, subscribeCollapsed } from './collapse'
import { type FlowerLayout, layoutFlowers, visibleFlowers } from './layout'
import { isKept } from './results'

export interface FlowerModel {
  /** The exploration's id. */
  id: string
  itemId: string
  key: string
  label: string
  /** The label of the part a physical dimension lives on; null for a whole-item one. */
  part: string | null
  /** Where the dashed line leaves the dimension's callout (its far edge; Whole item for a dimension gone from the analysis). */
  from: Point
  /** Angle from the item's centre to its callout: the flower opens this way. */
  dir: number
  /** The petals, in order: every option not dismissed. */
  options: ExploreOption[]
  collapsed: boolean
}

/**
 * A stable `combine` for useQueries (its result keeps its identity while no query changes): each
 * item's analysis, and whether any is still loading for the first time.
 */
const dataOf = (results: { data?: AnalysisView; isPending: boolean }[]) => ({
  data: results.map((r) => r.data),
  pending: results.some((r) => r.isPending),
})

const centre = (b: Bounds): Point => ({ x: b.x + b.width / 2, y: b.y + b.height / 2 })

/** Where a ray from `b`'s centre along `dir` leaves `b`. */
function edgePoint(b: Bounds, dir: number): Point {
  const c = centre(b)
  const dx = Math.cos(dir)
  const dy = Math.sin(dir)
  const t = Math.min(Math.abs(dx) > 1e-9 ? b.width / 2 / Math.abs(dx) : Infinity, Math.abs(dy) > 1e-9 ? b.height / 2 / Math.abs(dy) : Infinity)
  return { x: c.x + dx * t, y: c.y + dy * t }
}

/**
 * The flowers (one per exploration on a visible item whose analysis has loaded: a flower is never
 * drawn at a guessed spot and then moved) and each of their items' callout cards (obstacles).
 */
export function mapModel(
  explorations: readonly Exploration[],
  items: readonly Item[],
  analyses: ReadonlyMap<string, AnalysisView | undefined>,
  collapsed: (id: string) => boolean,
  labels: ReadonlyMap<string, string>,
): { flowers: FlowerModel[]; callouts: Map<string, Bounds[]> } {
  const byId = new Map(items.map((i) => [i.id, i]))
  const slots = new Map<string, Map<string, Bounds>>()
  for (const itemId of new Set(explorations.map((e) => e.item_id))) {
    const item = byId.get(itemId)
    const analysis = analyses.get(itemId)
    if (!item || !analysis) continue
    // the same slots the callouts take when shown, before any flower is around: every other item
    slots.set(itemId, calloutBounds(item, analysis, items.filter((i) => i.id !== itemId).map(itemBounds)))
  }
  const flowers: FlowerModel[] = []
  for (const e of explorations) {
    const item = byId.get(e.item_id)
    const analysis = analyses.get(e.item_id)
    const slot = slots.get(e.item_id)?.get(analysis ? (cardOf(analysis, e.key) ?? WHOLE) : WHOLE)
    if (!item || !analysis || !slot) continue
    const c = centre(slot)
    const ic = centre(itemBounds(item))
    const dir = Math.atan2(c.y - ic.y, c.x - ic.x)
    const dim = analysis.dimensions.find((d) => d.key === e.key)
    const label = dim?.label ?? labels.get(e.key) ?? e.key
    const part = dim?.type === 'physical' ? (analysis.parts.find((p) => p.key === dim.part)?.label ?? null) : null
    flowers.push({
      id: e.id,
      itemId: e.item_id,
      key: e.key,
      label,
      part,
      from: edgePoint(slot, dir),
      dir,
      options: optionTree(e.options).map((r) => r.option),
      collapsed: collapsed(e.id),
    })
  }
  const callouts = new Map([...slots].map(([id, m]) => [id, [...m.values()]]))
  return { flowers, callouts }
}

/**
 * Every flower is laid out (collapsed ones too, so collapsing never moves another flower), but only
 * once every analysis they start from has loaded, so the layout never depends on arrival order. Only
 * those reaching `viewport` (canvas units) come back in `flowers`. `obstacles` are the items and
 * callouts the layout avoided (with `layouts`, what a kept result must stay clear of).
 */
export interface MapView {
  flowers: FlowerModel[]
  layouts: Map<string, FlowerLayout>
  obstacles: Bounds[]
}

export function useMap(boardId: string, items: readonly Item[], viewport: Bounds): MapView {
  const { exploreEnabled } = useDemo()
  const explorations = useExplorations(boardId).data
  const lensAttrs = useBoardLens(boardId).data?.spec.attributes
  const version = useSyncExternalStore(subscribeCollapsed, collapsedVersion)
  const shown = useMemo(() => {
    if (!exploreEnabled || !explorations) return []
    const on = new Set(items.map((i) => i.id))
    return explorations.filter((e) => on.has(e.item_id))
  }, [exploreEnabled, explorations, items])
  const itemIds = useMemo(() => [...new Set(shown.map((e) => e.item_id))].sort(), [shown])
  const analysisData = useQueries({
    queries: itemIds.map((id) => ({ queryKey: keys.analysis(id), queryFn: () => getAnalysis(id) })),
    combine: dataOf,
  })
  const analyses = useMemo(
    () => (analysisData.pending ? null : new Map(itemIds.map((id, i) => [id, analysisData.data[i]]))),
    [itemIds, analysisData],
  )
  const labels = useMemo(() => new Map((lensAttrs ?? []).map((a) => [a.key, a.label])), [lensAttrs])

  const map = useMemo(() => {
    void version // re-read the collapsed flags when one changes
    const itemBoxes = items.map(itemBounds)
    if (!analyses) return { flowers: [], layouts: new Map<string, FlowerLayout>(), obstacles: itemBoxes }
    const { flowers, callouts } = mapModel(shown, items, analyses, (id) => isCollapsed(boardId, id), labels)
    const layouts = layoutFlowers(
      flowers.map((f) => ({
        id: f.id,
        itemId: f.itemId,
        from: f.from,
        dir: f.dir,
        petals: f.options.length,
        kept: f.options.flatMap((o, i) => (isKept(o) ? [i] : [])),
      })),
      itemBoxes,
      callouts,
    )
    return { flowers, layouts, obstacles: [...itemBoxes, ...[...callouts.values()].flat()] }
  }, [shown, items, analyses, labels, boardId, version])

  const { x, y, width, height } = viewport
  const flowers = useMemo(() => {
    const on = new Set(visibleFlowers(map.layouts, { x, y, width, height }))
    return map.flowers.filter((f) => on.has(f.id))
  }, [map, x, y, width, height])
  return { flowers, layouts: map.layouts, obstacles: map.obstacles }
}
