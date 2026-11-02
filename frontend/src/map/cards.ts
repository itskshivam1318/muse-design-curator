/** The callout cards around an item: which card a dimension sits on, and each card's size. */
import type { AnalysisView, Item } from '../api'
import { CALLOUT_W } from '../living/ring'

/** The Whole item card's key among the part keys (part keys are slugs: no colon). */
export const WHOLE = 'whole:item'

// card geometry (canvas units), mirrored by the .callout CSS
const PAD = 8
const HEAD_H = 24
const ROW_H = 30
const ROW_GAP = 4
const FORM_H = 34

/** The card's height for its rows: header, one row per dimension, the action row, open forms. */
const cardHeight = (rows: number, actionRows: number, forms: number) =>
  PAD * 2 + HEAD_H + (rows + actionRows) * (ROW_H + ROW_GAP) + forms * FORM_H

/**
 * Whether the Whole item card offers "+ Add part": images only this phase. A note's part needs a
 * text range and a UI screenshot's a box (no segmentation for UI), which a name alone cannot give.
 */
export function canAddPart(item: Item, analysis: AnalysisView): boolean {
  if (item.kind !== 'image' && item.kind !== 'video') return false
  return (analysis.content_type ?? item.content_type) !== 'ui'
}

/** The card a dimension sits on: its part's, or Whole item (abstract, or a part that is gone). */
export function cardOf(analysis: AnalysisView, key: string): string | null {
  const d = analysis.dimensions.find((x) => x.key === key)
  if (!d) return null
  return d.type === 'physical' && d.part && analysis.parts.some((p) => p.key === d.part) ? d.part : WHOLE
}

/** A card's size: the callout width, and the height its rows (and `forms` open add-forms) need. */
export function calloutSize(item: Item, analysis: AnalysisView, card: string, forms = 0): { w: number; h: number } {
  if (card === WHOLE) {
    const abstract = analysis.dimensions.filter((d) => d.type === 'abstract').length
    return { w: CALLOUT_W, h: cardHeight(abstract, canAddPart(item, analysis) ? 2 : 1, forms) }
  }
  const rows = analysis.dimensions.filter((d) => d.type === 'physical' && d.part === card).length
  return { w: CALLOUT_W, h: cardHeight(rows, 1, forms) }
}
