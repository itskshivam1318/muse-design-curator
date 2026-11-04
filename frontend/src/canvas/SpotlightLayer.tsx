import { useEffect, useRef } from 'react'
import { isTyping } from '../pages/shortcutGuard'
import { backSpot, closeSpotlight, currentStep, nextSpot, type Spotlight } from '../shell/spotlight'
import type { Bounds } from './geometry'

const PAD = 8 // screen px of room around a lit item
const RADIUS = 10
const GAP = 12 // between the lit items and the card
const CARD_W = 320
const CARD_H = 150 // room kept for the card when deciding where it fits

const roundedRect = (b: Bounds) => {
  const x = b.x - PAD
  const y = b.y - PAD
  const w = b.width + PAD * 2
  const h = b.height + PAD * 2
  const r = Math.min(RADIUS, w / 2, h / 2)
  return (
    `M${x + r} ${y}H${x + w - r}A${r} ${r} 0 0 1 ${x + w} ${y + r}V${y + h - r}` +
    `A${r} ${r} 0 0 1 ${x + w - r} ${y + h}H${x + r}A${r} ${r} 0 0 1 ${x} ${y + h - r}` +
    `V${y + r}A${r} ${r} 0 0 1 ${x + r} ${y}Z`
  )
}

function cardPosition(lit: Bounds[], size: { width: number; height: number }): { left: number; top: number } {
  const centred = { left: (size.width - CARD_W) / 2, top: (size.height - CARD_H) / 2 }
  if (lit.length === 0) return centred
  const left0 = Math.min(...lit.map((b) => b.x - PAD))
  const right = Math.max(...lit.map((b) => b.x + b.width + PAD))
  const top0 = Math.min(...lit.map((b) => b.y - PAD))
  const bottom = Math.max(...lit.map((b) => b.y + b.height + PAD))
  const left = Math.max(GAP, Math.min((left0 + right) / 2 - CARD_W / 2, size.width - CARD_W - GAP))
  if (bottom + GAP + CARD_H <= size.height) return { left, top: bottom + GAP }
  if (top0 - GAP - CARD_H >= 0) return { left, top: top0 - GAP - CARD_H }
  return centred
}

/**
 * The spotlight over the stage: a translucent dim with a hole around each of the step's pictures,
 * and a caption card with Back / Next / Done. The dim lets pointer events through to the board.
 */
export function SpotlightLayer({
  spotlight,
  lit,
  size,
}: {
  spotlight: Spotlight
  lit: Bounds[]
  size: { width: number; height: number }
}) {
  const nextRef = useRef<HTMLButtonElement>(null)
  const step = currentStep(spotlight)

  useEffect(() => {
    nextRef.current?.focus()
  }, [])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (isTyping(e.target)) return
      const act = e.key === 'Escape' ? closeSpotlight : e.key === 'ArrowRight' ? nextSpot : e.key === 'ArrowLeft' ? backSpot : null
      if (!act) return
      e.stopImmediatePropagation()
      e.preventDefault()
      act()
    }
    window.addEventListener('keydown', onKey, true)
    return () => window.removeEventListener('keydown', onKey, true)
  }, [])

  if (!step) return null
  const count = spotlight.steps.length
  const last = spotlight.index === count - 1
  const d = `M0 0H${size.width}V${size.height}H0Z` + lit.map(roundedRect).join('')
  const pos = cardPosition(lit, size)

  return (
    <>
      <svg className="spotlight-svg" width={size.width} height={size.height} aria-hidden="true">
        <path className="spotlight-dim" d={d} fillRule="evenodd" fill="rgba(20, 18, 16, 0.45)" />
      </svg>
      <div className="spotlight-card" role="dialog" aria-label="Replay" style={pos}>
        <div className="spotlight-card-head">
          <span className="spotlight-turn">Step {step.turn}</span>
          <button type="button" className="icon-btn" aria-label="Close replay" onClick={closeSpotlight}>
            ×
          </button>
        </div>
        <p className="spotlight-say">{step.say || step.tool}</p>
        {lit.length === 0 && <p className="spotlight-gone">This step's pictures are no longer on the board.</p>}
        <div className="spotlight-foot">
          <span className="spotlight-count">
            {spotlight.index + 1} of {count}
          </span>
          <span className="spotlight-actions">
            <button type="button" className="btn-quiet small" disabled={spotlight.index === 0} onClick={backSpot}>
              Back
            </button>
            <button type="button" className="btn small" ref={nextRef} onClick={nextSpot}>
              {last ? 'Done' : 'Next'}
            </button>
          </span>
        </div>
      </div>
    </>
  )
}
