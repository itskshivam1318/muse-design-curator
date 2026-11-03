/** Aiming for "put into": which spots a line's end picks on the target picture. Pure. */
import type { AnalysisView, PartView, PutSpot } from '../api'

export type Spot = { kind: 'part'; part: PartView } | { kind: 'point'; fx: number; fy: number }

/** The last word of a label, lower-cased, with a plural `s` dropped ("Rear Wheels" -> "wheel"). */
export function headNoun(label: string): string {
  const words = label.trim().split(/\s+/)
  const w = (words[words.length - 1] ?? '').toLowerCase()
  return w.endsWith('s') && !w.endsWith('ss') ? w.slice(0, -1) : w
}

const hasBox = (p: PartView) => p.region_kind !== 'text_range' && p.region?.length === 4

/** The smallest box part containing the point, or null. */
export function partAt(parts: readonly PartView[], fx: number, fy: number): PartView | null {
  let best: PartView | null = null
  let bestArea = Infinity
  for (const p of parts) {
    if (!hasBox(p)) continue
    const [x0, y0, x1, y1] = p.region as number[]
    if (fx < x0 || fx > x1 || fy < y0 || fy > y1) continue
    const area = (x1 - x0) * (y1 - y0)
    if (area < bestArea) {
      best = p
      bestArea = area
    }
  }
  return best
}

/** The aimed part first, then every other part of the same head noun in order (a part with no box is still offered; text ranges are not). */
export function sameKind(parts: readonly PartView[], aimed: PartView): PartView[] {
  const noun = headNoun(aimed.label)
  return [aimed, ...parts.filter((p) => p !== aimed && p.key !== aimed.key && p.region_kind !== 'text_range' && headNoun(p.label) === noun)]
}

export function aimAt(analysis: AnalysisView | null | undefined, fx: number, fy: number): Spot[] {
  const parts = analysis?.parts ?? []
  const hit = partAt(parts, fx, fy)
  if (!hit) return [{ kind: 'point', fx, fy }]
  return sameKind(parts, hit).map((part) => ({ kind: 'part', part }))
}

/** The request spots, leaving out the indices the person switched off. */
export function toBody(spots: readonly Spot[], off: ReadonlySet<number>): PutSpot[] {
  return spots.flatMap((s, i): PutSpot[] =>
    off.has(i) ? [] : s.kind === 'part' ? [{ part: s.part.key }] : [{ point: { fx: s.fx, fy: s.fy } }],
  )
}

export const spotLabel = (s: Spot): string => (s.kind === 'part' ? s.part.label : 'Here')
