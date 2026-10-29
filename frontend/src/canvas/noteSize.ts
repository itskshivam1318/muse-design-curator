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

/** A note item with the size the canvas draws it at (fixed width, height from its text). */
export const sizedNote = (item: Item): Item =>
  item.kind === 'note' ? { ...item, w: NOTE_W, h: noteHeight(item.note_text) } : item
