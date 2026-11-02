/**
 * The board's living scene: the items, every exploration on them and the analyses they start from
 * (and the selected item's, for its callouts) gathered from the queries and built into bodies and
 * edges by `buildScene`.
 */
import { useQueries } from '@tanstack/react-query'
import { useMemo, useSyncExternalStore } from 'react'
import { type AnalysisView, getAnalysis, type Item, keys } from '../api'
import { useDemo } from '../demo'
import { collapsedVersion, isCollapsed, subscribeCollapsed } from '../map/collapse'
import { useBoardLens, useExplorations } from '../queries'
import { buildScene, type Scene } from './scene'

/**
 * A stable `combine` for useQueries (its result keeps its identity while no query changes): each
 * item's analysis once settled, null when it failed, undefined while loading.
 */
const dataOf = (results: { data?: AnalysisView; isPending: boolean }[]): (AnalysisView | null | undefined)[] =>
  results.map((r) => r.data ?? (r.isPending ? undefined : null))

const NO_HEIGHTS: Readonly<Record<string, number>> = {}

/**
 * `selectedId` is the item whose callouts show (null: none). `calloutHeights` are its cards' drawn
 * heights and `toolbar` the selection toolbar's size (both canvas units), see `SceneInput`.
 */
export function useLivingScene(
  boardId: string,
  items: readonly Item[],
  selectedId: string | null,
  extra: { calloutHeights?: Readonly<Record<string, number>>; toolbar?: { w: number; h: number } } = {},
): Scene {
  const { calloutHeights = NO_HEIGHTS, toolbar } = extra
  const { exploreEnabled } = useDemo()
  const explorations = useExplorations(boardId).data
  const lensAttrs = useBoardLens(boardId).data?.spec.attributes
  const version = useSyncExternalStore(subscribeCollapsed, collapsedVersion)
  const shown = useMemo(() => {
    if (!exploreEnabled || !explorations) return []
    const on = new Set(items.map((i) => i.id))
    return explorations.filter((e) => on.has(e.item_id))
  }, [exploreEnabled, explorations, items])
  const itemIds = useMemo(
    () => [...new Set([...shown.map((e) => e.item_id), ...(selectedId ? [selectedId] : [])])].sort(),
    [shown, selectedId],
  )
  const analysisData = useQueries({
    // one retry: a failing analysis settles soon and stops holding back its flowers
    queries: itemIds.map((id) => ({ queryKey: keys.analysis(id), queryFn: () => getAnalysis(id), retry: 1 })),
    combine: dataOf,
  })
  const analyses = useMemo(() => new Map(itemIds.map((id, i) => [id, analysisData[i]])), [itemIds, analysisData])
  const labels = useMemo(() => new Map((lensAttrs ?? []).map((a) => [a.key, a.label])), [lensAttrs])

  return useMemo(() => {
    void version // re-read the collapsed flags when one changes
    return buildScene({
      items,
      explorations: shown,
      analyses,
      labels,
      collapsed: (id) => isCollapsed(boardId, id),
      selectedId,
      calloutHeights: new Map(Object.entries(calloutHeights)),
      toolbar,
    })
  }, [items, shown, analyses, labels, boardId, version, selectedId, calloutHeights, toolbar])
}
