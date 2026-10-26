import { useEffect, useState } from 'react'

export interface CanvasPalette {
  accent: string
  ink: string
  paper: string
  panel: string
  muted: string
  rule: string
  ok: string
  warn: string
  bad: string
}

const FALLBACK: CanvasPalette = {
  accent: '#2a4aae', ink: '#14181e', paper: '#eceff2', panel: '#f8f9fb', muted: '#566170',
  rule: '#c8ced7', ok: '#2c7a4b', warn: '#9a6110', bad: '#ad3636',
}

function read(): CanvasPalette {
  if (typeof window === 'undefined') return FALLBACK
  const cs = getComputedStyle(document.documentElement)
  const v = (name: string, fb: string) => cs.getPropertyValue(name).trim() || fb
  return {
    accent: v('--accent', FALLBACK.accent),
    ink: v('--ink', FALLBACK.ink),
    paper: v('--paper', FALLBACK.paper),
    panel: v('--panel', FALLBACK.panel),
    muted: v('--muted', FALLBACK.muted),
    rule: v('--rule', FALLBACK.rule),
    ok: v('--ok', FALLBACK.ok),
    warn: v('--warn', FALLBACK.warn),
    bad: v('--bad', FALLBACK.bad),
  }
}

/** Konva draws with real colours, so read the CSS tokens and re-read when the theme flips. */
export function useCanvasPalette(): CanvasPalette {
  const [p, setP] = useState(read)
  useEffect(() => {
    const mq = window.matchMedia?.('(prefers-color-scheme: dark)')
    const on = () => setP(read())
    mq?.addEventListener('change', on)
    return () => mq?.removeEventListener('change', on)
  }, [])
  return p
}

export function usePrefersReducedMotion(): boolean {
  const query = '(prefers-reduced-motion: reduce)'
  const [reduced, setReduced] = useState(() => window.matchMedia?.(query).matches ?? false)
  useEffect(() => {
    const mq = window.matchMedia?.(query)
    const on = () => setReduced(mq.matches)
    mq?.addEventListener('change', on)
    return () => mq?.removeEventListener('change', on)
  }, [])
  return reduced
}
