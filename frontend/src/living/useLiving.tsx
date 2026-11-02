import { createContext, useContext, useEffect, type ReactNode, type RefObject } from 'react'
import { growScale } from './physics'
import type { LivingWorld } from './world'

const LivingContext = createContext<LivingWorld | null>(null)

export function LivingProvider({ world, children }: { world: LivingWorld; children: ReactNode }) {
  return <LivingContext.Provider value={world}>{children}</LivingContext.Provider>
}

export function useLivingWorld(): LivingWorld {
  const w = useContext(LivingContext)
  if (!w) throw new Error('useLivingWorld must be used inside a LivingProvider')
  return w
}

/** Writes `transform` (translate to top-left + grow scale), size and opacity onto ref.current every frame. */
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
      el.style.width = `${b.w}px`
      el.style.height = `${b.h}px`
      el.style.transform = `translate(${b.x - b.w / 2}px, ${b.y - b.h / 2}px) scale(${s})`
      el.style.opacity = String(Math.min(1, s * 1.6))
    }
    return world.onFrame(write)
  }, [world, id, ref])
}
