import { useEffect, useReducer } from 'react'

const cache = new Map<string, HTMLImageElement>()

function load(src: string): HTMLImageElement {
  let el = cache.get(src)
  if (!el) {
    el = new Image()
    el.decoding = 'async'
    el.addEventListener('error', () => cache.delete(src), { once: true })
    el.src = src
    cache.set(src, el)
  }
  return el
}

const ready = (el: HTMLImageElement | undefined) => !!el && el.complete && el.naturalWidth > 0

/** A loaded image element for Konva, or undefined until it has loaded. */
export function useImage(src: string | null): HTMLImageElement | undefined {
  const [, rerender] = useReducer((n: number) => n + 1, 0)
  const el = src ? load(src) : undefined
  useEffect(() => {
    if (!el || ready(el)) return
    el.addEventListener('load', rerender)
    return () => el.removeEventListener('load', rerender)
  }, [el])
  return ready(el) ? el : undefined
}
