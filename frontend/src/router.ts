/** A minimal history router: two routes, no dependency. */
import { useSyncExternalStore } from 'react'

const NAV_EVENT = 'app:navigate'

function subscribe(cb: () => void) {
  window.addEventListener('popstate', cb)
  window.addEventListener(NAV_EVENT, cb)
  return () => {
    window.removeEventListener('popstate', cb)
    window.removeEventListener(NAV_EVENT, cb)
  }
}

export function usePathname(): string {
  return useSyncExternalStore(subscribe, () => window.location.pathname)
}

export function navigate(to: string, opts: { replace?: boolean } = {}): void {
  if (opts.replace) window.history.replaceState(null, '', to)
  else window.history.pushState(null, '', to)
  window.dispatchEvent(new Event(NAV_EVENT))
}

export type Route = { name: 'boards' } | { name: 'board'; id: string } | { name: 'not-found' }

export function matchRoute(path: string): Route {
  if (path === '/' || path === '') return { name: 'boards' }
  const m = /^\/boards\/([^/]+)\/?$/.exec(path)
  if (m) return { name: 'board', id: decodeURIComponent(m[1]) }
  return { name: 'not-found' }
}
