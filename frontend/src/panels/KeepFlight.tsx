import { useLayoutEffect, useRef } from 'react'
import type { Bounds } from '../canvas/geometry'

export const FLIGHT_MS = 420

/**
 * A kept candidate flies from the popover onto the canvas beside its source: one short transform
 * animation on a copy of the image. Callers skip it under prefers-reduced-motion.
 */
export function KeepFlight({ src, from, to, onDone }: { src: string; from: Bounds; to: Bounds; onDone: () => void }) {
  const ref = useRef<HTMLImageElement>(null)
  const done = useRef(onDone)
  useLayoutEffect(() => {
    done.current = onDone
  })
  useLayoutEffect(() => {
    const el = ref.current
    if (!el || typeof el.animate !== 'function' || from.width === 0 || from.height === 0) {
      done.current()
      return
    }
    const dx = to.x - from.x
    const dy = to.y - from.y
    const sx = to.width / from.width
    const sy = to.height / from.height
    const anim = el.animate(
      [{ transform: 'translate(0, 0) scale(1, 1)' }, { transform: `translate(${dx}px, ${dy}px) scale(${sx}, ${sy})` }],
      { duration: FLIGHT_MS, easing: 'cubic-bezier(0.2, 0.7, 0.2, 1)', fill: 'forwards' },
    )
    anim.onfinish = () => done.current()
    return () => anim.cancel()
  }, [from, to])
  return (
    <img
      ref={ref}
      src={src}
      alt=""
      aria-hidden="true"
      className="keep-flight"
      style={{ left: from.x, top: from.y, width: from.width, height: from.height }}
    />
  )
}
