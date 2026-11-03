/** The "put into" line's state: idle, being dragged from a picture's dot, or let go on a target (the card). */
import { useCallback, useMemo, useState } from 'react'
import type { Item, Point } from '../api'
import type { Bounds } from '../canvas/geometry'
import type { Spot } from './spots'

/** Points are in canvas units. */
export type Connect =
  | { phase: 'idle' }
  | { phase: 'drag'; sourceId: string; at: Point; targetId: string | null; spots: Spot[] }
  | {
      phase: 'card'
      sourceId: string
      targetId: string
      end: Point
      spots: Spot[]
      off: Set<number>
      /** The card's centre, fixed when it opens (it holds its place; the board moves round it). */
      cardAt: Point | null
      /** Where the line ends on the target (fractions of it), so the end follows it when it moves. */
      endOn: { fx: number; fy: number } | null
    }

const IDLE: Connect = { phase: 'idle' }

/** Where a card opening on a line goes, worked out from the line as it is let go. */
export type Placed = { cardAt: Point; endOn: { fx: number; fy: number } }

export function useConnect() {
  const [state, setState] = useState<Connect>(IDLE)
  const start = useCallback((sourceId: string, at: Point) => setState({ phase: 'drag', sourceId, at, targetId: null, spots: [] }), [])
  const move = useCallback(
    (at: Point, hit: { targetId: string | null; spots: Spot[] }) =>
      setState((s) => (s.phase === 'drag' ? { ...s, at, targetId: hit.targetId, spots: hit.targetId ? hit.spots : [] } : s)),
    [],
  )
  // a card only when the line ends on a target with a spot; anything else leaves nothing behind
  const release = useCallback(
    (place?: (line: { sourceId: string; targetId: string; at: Point }) => Placed | null) =>
      setState((s) => {
        if (s.phase !== 'drag') return s
        if (!s.targetId || s.spots.length === 0) return IDLE
        const { cardAt = null, endOn = null } = place?.({ sourceId: s.sourceId, targetId: s.targetId, at: s.at }) ?? {}
        return { phase: 'card', sourceId: s.sourceId, targetId: s.targetId, end: s.at, spots: s.spots, off: new Set(), cardAt, endOn }
      }),
    [],
  )
  const toggle = useCallback(
    (i: number) =>
      setState((s) => {
        if (s.phase !== 'card') return s
        const off = new Set(s.off)
        if (off.has(i)) off.delete(i)
        else off.add(i)
        return { ...s, off }
      }),
    [],
  )
  const cancel = useCallback(() => setState(IDLE), [])
  return useMemo(() => ({ state, start, move, release, toggle, cancel }), [state, start, move, release, toggle, cancel])
}

/** The top-most (highest z) on-canvas image under `p`, never `except`; notes, links and videos never count. */
export function itemUnder(items: readonly Item[], bounds: (id: string) => Bounds | null, p: Point, except: string): Item | null {
  let best: Item | null = null
  for (const i of items) {
    if (i.kind !== 'image' || i.staged || i.id === except) continue
    const b = bounds(i.id)
    if (!b || p.x < b.x || p.x > b.x + b.width || p.y < b.y || p.y > b.y + b.height) continue
    if (!best || i.z > best.z) best = i
  }
  return best
}
