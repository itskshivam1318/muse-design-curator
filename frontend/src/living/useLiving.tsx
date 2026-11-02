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
 * mount (so it never shows unplaced), then every frame.
 */
export function useBodyElement(id: string, ref: RefObject<HTMLElement | null>): void {
  const world = useLivingWorld()
  useEffect(() => {
    const write = (now: number): void => {
      const el = ref.current
      if (!el) return
      const b = world.body(id)
      if (!b) {
        el.style.opacity = '0'
        return
      }
      const s = growScale(b, now, world.reduced())
      // to 0.01px: a body at rest keeps an identical style (no float noise), so it reads as still
      el.style.width = `${r2(b.w)}px`
      el.style.height = `${r2(b.h)}px`
      el.style.transform = `translate(${r2(b.x - b.w / 2)}px, ${r2(b.y - b.h / 2)}px) scale(${r2(s)})`
      el.style.opacity = String(Math.min(1, s * 1.6))
    }
    write(world.now())
    return world.onFrame(write)
  }, [world, id, ref])
}
