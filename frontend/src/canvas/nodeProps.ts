/**
 * Rendering decisions for canvas nodes as pure functions.
 * Images are drawn with no border, no radius, no padding and no shadow; everything that marks
 * state (hover, status, selection) is drawn outside the image bounds or over it, never as a frame.
 */
import type { Item, ParseStatus } from '../api'
import type { Bounds } from './geometry'

export const HOVER_GAP = 4 // screen px between image edge and hover outline
export const OUTLINE_WIDTH = 1
export const DOT_SIZE = 8
export const DOT_OFFSET = 9 // dot centre sits this far outside the top-left corner
export const HANDLE_SIZE = 9
export const HANDLE_GAP = 1 // screen px between image corner and handle
export const SHIMMER_OPACITY = 0.08

export const itemBounds = (i: Pick<Item, 'x' | 'y' | 'w' | 'h'>): Bounds => ({
  x: i.x,
  y: i.y,
  width: i.w,
  height: i.h,
})

export function imageNodeProps(item: Pick<Item, 'id' | 'x' | 'y' | 'w' | 'h'>) {
  return {
    id: item.id,
    x: item.x,
    y: item.y,
    width: item.w,
    height: item.h,
    strokeWidth: 0,
    strokeEnabled: false,
    cornerRadius: 0,
    shadowEnabled: false,
    shadowForStrokeEnabled: false,
    perfectDrawEnabled: false,
  } as const
}

/** 1 px outline, 4 px outside the image, constant in screen pixels at any zoom. */
export function hoverOutlineRect(b: Bounds, scale: number) {
  const gap = HOVER_GAP / scale
  return {
    x: b.x - gap,
    y: b.y - gap,
    width: b.width + gap * 2,
    height: b.height + gap * 2,
    strokeWidth: OUTLINE_WIDTH / scale,
    fillEnabled: false,
    listening: false,
  }
}

/** 8 px parse-status dot just outside the top-left corner (further out when handles are shown). */
export function statusDot(b: Bounds, scale: number, selected = false) {
  const off = (selected ? DOT_OFFSET + HANDLE_SIZE + HANDLE_GAP : DOT_OFFSET) / scale
  return {
    x: b.x - off,
    y: b.y - off,
    radius: DOT_SIZE / 2 / scale,
    listening: false,
  }
}

/** Four square handles, each fully outside its corner of the image. */
export function handleRects(b: Bounds, scale: number) {
  const s = HANDLE_SIZE / scale
  const g = HANDLE_GAP / scale
  const left = b.x - g - s
  const right = b.x + b.width + g
  const top = b.y - g - s
  const bottom = b.y + b.height + g
  return [
    { key: 'tl', x: left, y: top },
    { key: 'tr', x: right, y: top },
    { key: 'bl', x: left, y: bottom },
    { key: 'br', x: right, y: bottom },
  ].map((h) => ({ ...h, width: s, height: s, strokeWidth: 1.5 / scale, listening: false }))
}

export const isParsing = (s: ParseStatus) => s === 'pending' || s === 'processing'

export function statusColor(
  s: ParseStatus,
  palette: { muted: string; warn: string; ok: string; bad: string },
): string {
  switch (s) {
    case 'completed':
      return palette.ok
    case 'failed':
      return palette.bad
    case 'processing':
      return palette.warn
    default:
      return palette.muted
  }
}

export function statusLabel(item: Pick<Item, 'parse_status' | 'parse_error_code'>): string {
  switch (item.parse_status) {
    case 'pending':
      return 'Waiting to parse'
    case 'pending_lens':
      return 'Waiting for the board lens'
    case 'processing':
      return 'Parsing…'
    case 'completed':
      return 'Parsed'
    case 'failed':
      return `Could not parse${item.parse_error_code ? ` (${item.parse_error_code})` : ''}`
  }
}

/** Thin curve from the parent's right edge to the kept item's left edge (cubic Bézier). */
export function lineagePoints(parent: Bounds, child: Bounds): number[] {
  const leftToRight = parent.x + parent.width / 2 <= child.x + child.width / 2
  const sx = leftToRight ? parent.x + parent.width : parent.x
  const sy = parent.y + parent.height / 2
  const ex = leftToRight ? child.x : child.x + child.width
  const ey = child.y + child.height / 2
  const pull = Math.max(40, Math.abs(ex - sx) / 2) * (leftToRight ? 1 : -1)
  return [sx, sy, sx + pull, sy, ex - pull, ey, ex, ey]
}

/** Image source for an item at its on-screen size: the 512 px thumbnail unless it is shown larger. */
export function wantsFull(item: Pick<Item, 'w' | 'h'>, scale: number, dpr = 1): boolean {
  return Math.max(item.w, item.h) * scale * dpr > 512
}
