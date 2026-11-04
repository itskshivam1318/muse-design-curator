/**
 * The part the agent asks about, over its item on the board (HTML over the canvas): the mask tinted pink,
 * the box outlined. In `draw` mode a drag over the item draws a new box and answers with it; Esc goes back.
 */
import { type PointerEvent as ReactPointerEvent, useEffect, useId, useRef, useState } from 'react'
import { API_ORIGIN, type Point } from '../api'
import { boxBounds } from '../map/regions'
import { type PartConfirm, partConfirmStore, setConfirmMode } from '../shell/partConfirm'
import { type Bounds, normalizeRect } from './geometry'

const TINT = '#ff4f9a'
const TINT_ALPHA = 0.55
/** A drag shorter than this (screen px) either way is a click, not a box. */
const MIN_DRAG = 4

/** Mask URLs come as `/api/media/…`: served from the API origin. */
const maskSrc = (url: string) => (/^https?:/.test(url) ? url : `${API_ORIGIN}${url}`)

const clamp01 = (v: number) => Math.min(1, Math.max(0, v))

export function PartConfirmLayer({ confirm, screen }: { confirm: PartConfirm; screen: Bounds }) {
  const filterId = `part-confirm-${useId().replace(/:/g, '')}`
  const pad = useRef<HTMLDivElement>(null)
  // the drag, in screen px from the item's top-left
  const [drag, setDrag] = useState<{ a: Point; b: Point } | null>(null)
  const drawing = confirm.mode === 'draw'

  useEffect(() => {
    if (!drawing) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return
      e.stopImmediatePropagation()
      e.preventDefault()
      setDrag(null)
      setConfirmMode('show')
    }
    window.addEventListener('keydown', onKey, true)
    return () => window.removeEventListener('keydown', onKey, true)
  }, [drawing])

  const local = (e: ReactPointerEvent): Point => {
    const r = pad.current!.getBoundingClientRect()
    return { x: e.clientX - r.left, y: e.clientY - r.top }
  }
  const onDown = (e: ReactPointerEvent<HTMLDivElement>) => {
    if (e.button !== 0) return
    e.currentTarget.setPointerCapture?.(e.pointerId)
    const p = local(e)
    setDrag({ a: p, b: p })
  }
  const onMove = (e: ReactPointerEvent) => {
    if (drag) setDrag({ a: drag.a, b: local(e) })
  }
  const onUp = (e: ReactPointerEvent) => {
    if (!drag) return
    setDrag(null)
    const r = normalizeRect(drag.a, local(e))
    if (r.width < MIN_DRAG || r.height < MIN_DRAG || screen.width <= 0 || screen.height <= 0) return
    const box = [
      clamp01(r.x / screen.width),
      clamp01(r.y / screen.height),
      clamp01((r.x + r.width) / screen.width),
      clamp01((r.y + r.height) / screen.height),
    ]
    partConfirmStore.set({ ...confirm, box, mode: 'show' })
    confirm.answer({ call_id: confirm.callId, box })
  }

  const at = { left: screen.x, top: screen.y, width: screen.width, height: screen.height }
  const shown = drag ? normalizeRect(drag.a, drag.b) : null
  const boxStyle = (b: Bounds) => ({ left: b.x, top: b.y, width: b.width, height: b.height })
  const outline = shown
    ? boxStyle({ ...shown, x: screen.x + shown.x, y: screen.y + shown.y })
    : confirm.box
      ? boxStyle(boxBounds(screen, confirm.box))
      : null
  return (
    <>
      {confirm.maskUrl && (
        <svg className="part-confirm-mask" style={at} width={screen.width} height={screen.height} aria-hidden="true">
          <defs>
            <filter id={filterId} x="0" y="0" width="1" height="1" colorInterpolationFilters="sRGB">
              <feColorMatrix in="SourceGraphic" type="luminanceToAlpha" result="part" />
              <feFlood floodColor={TINT} floodOpacity={TINT_ALPHA} />
              <feComposite in2="part" operator="in" />
            </filter>
          </defs>
          <image
            href={maskSrc(confirm.maskUrl)}
            width={screen.width}
            height={screen.height}
            preserveAspectRatio="none"
            filter={`url(#${filterId})`}
          />
        </svg>
      )}
      {outline && <div className="part-confirm-box" style={outline} aria-hidden="true" />}
      {drawing && (
        <div
          ref={pad}
          className="part-confirm-draw"
          style={at}
          role="application"
          aria-label="Drag a box over the part"
          onPointerDown={onDown}
          onPointerMove={onMove}
          onPointerUp={onUp}
          onPointerCancel={() => setDrag(null)}
        />
      )}
    </>
  )
}
