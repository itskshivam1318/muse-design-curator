/** How big a note is drawn: a fixed width, and a height that follows its wrapped text. */
import Konva from 'konva'
import type { Item } from '../api'

export const NOTE_W = 220
export const NOTE_MIN_H = 96
export const NOTE_PAD = 16
export const NOTE_FILL = '#fff6d9'
export const NOTE_INK = '#3a3220'
export const NOTE_FONT_SIZE = 14
export const NOTE_LINE_HEIGHT = 1.45
export const NOTE_FONT = "'IBM Plex Sans', system-ui, sans-serif"

export const noteTextProps = {
  width: NOTE_W,
  padding: NOTE_PAD,
  fontSize: NOTE_FONT_SIZE,
  fontFamily: NOTE_FONT,
  lineHeight: NOTE_LINE_HEIGHT,
  wrap: 'word',
} as const

const heights = new Map<string, number>()

/** The card height for a text (canvas units): the wrapped text plus padding, never under 96. */
export function noteHeight(text: string | null | undefined): number {
  const t = text ?? ''
  const known = heights.get(t)
  if (known !== undefined) return known
  let h = NOTE_MIN_H
  try {
    const probe = new Konva.Text({ ...noteTextProps, text: t })
    h = Math.max(NOTE_MIN_H, Math.ceil(probe.height()))
    probe.destroy()
  } catch {
    // no 2D canvas to measure with (some test environments): the minimum height stands
  }
  if (heights.size > 500) heights.clear()
  heights.set(t, h)
  return h
}

/**
 * A note item with the size the canvas draws it at: the note width, its height from its text. A kept
 * take (it docks small and undocks wide) keeps its stored width: it is laid out at the note width and
 * drawn scaled to it, its height in proportion.
 */
export function sizedNote(item: Item): Item {
  if (item.kind !== 'note') return item
  const w = item.explore_option_id && item.w > 0 ? item.w : NOTE_W
  return { ...item, w, h: (noteHeight(item.note_text) * w) / NOTE_W }
}

/** The highlighted passage's colour (the same yellow as a part's region on an image). */
export const HIGHLIGHT_FILL = '#ffd166'

type Band = { x: number; y: number; width: number; height: number }

/** One band per wrapped line the range [start, end) touches, in the note's own coordinates. */
export function highlightBands(text: string, start: number, end: number): Band[] {
  if (!(end > start)) return []
  let probe: Konva.Text
  try {
    probe = new Konva.Text({ ...noteTextProps, text })
  } catch {
    return [] // no 2D canvas to measure with
  }
  const lineH = NOTE_FONT_SIZE * NOTE_LINE_HEIGHT
  const bands: Band[] = []
  let cursor = 0
  probe.textArr.forEach((line, i) => {
    const at = text.indexOf(line.text, cursor)
    if (at === -1) return
    cursor = at + line.text.length
    const from = Math.max(start, at)
    const to = Math.min(end, cursor)
    if (to <= from) return
    const x = NOTE_PAD + probe.measureSize(line.text.slice(0, from - at)).width
    const width = probe.measureSize(line.text.slice(from - at, to - at)).width
    bands.push({ x, y: NOTE_PAD + i * lineH, width, height: lineH })
  })
  probe.destroy()
  return bands
}
