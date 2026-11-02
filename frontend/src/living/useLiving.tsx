import { createContext, useContext, useEffect, type ReactNode, type RefObject } from 'react'
import { growScale } from './physics'
import type { LivingWorld } from './world'

const r2 = (n: number) => Math.round(n * 100) / 100

const LivingContext = createContext<LivingWorld | null>(null)

export function LivingProvider({ world, children }: { world: LivingWorld; children: ReactNode }) {
  return <LivingContext.Provider value={world}>{children}</LivingContext.Provider>
}

export function useLivingWorld(): LivingWorld {
  const w = useContext(LivingContext)
  if (!w) throw new Error('useLivingWorld must be used inside a LivingProvider')
  return w
}

/**
 * Writes `transform` (translate to top-left + grow scale), size and opacity onto ref.current: once on
 * mount (so it never shows unplaced), then every frame, touching the style only when a rounded value
 * changed (a body at rest or asleep costs nothing). While it is not grown in (or has no body) the
 * element is `inert`: invisible things take no focus. With `ownHeight` the element keeps the height
 * its content gives it (the body is sized to match it).
 */
export function useBodyElement(id: string, ref: RefObject<HTMLElement | null>, opts: { ownHeight?: boolean } = {}): void {
  const world = useLivingWorld()
  const ownHeight = opts.ownHeight ?? false
  useEffect(() => {
    let last = ''
    let lastEl: HTMLElement | null = null
    const write = (now: number): void => {
      const el = ref.current
      if (!el) return
      // another element under the same ref (a hub becoming its badge): it has none of the style yet
      if (el !== lastEl) {
        lastEl = el
        last = ''
      }
      const b = world.body(id)
      const s = b ? growScale(b, now, world.reduced()) : 0
      // to 0.01px: a body at rest keeps an identical style (no float noise), so it reads as still
      const key = b ? `${r2(b.w)} ${r2(b.h)} ${r2(b.x - b.w / 2)} ${r2(b.y - b.h / 2)} ${r2(s)}` : 'none'
      if (key === last) return
      last = key
      el.toggleAttribute('inert', s === 0)
      if (!b) {
        el.style.opacity = '0'
        return
      }
      el.style.width = `${r2(b.w)}px`
      if (!ownHeight) el.style.height = `${r2(b.h)}px`
      el.style.transform = `translate(${r2(b.x - b.w / 2)}px, ${r2(b.y - b.h / 2)}px) scale(${r2(s)})`
      el.style.opacity = String(Math.min(1, s * 1.6))
    }
    write(world.now())
    return world.onFrame(write)
  }, [world, id, ref, ownHeight])
}
