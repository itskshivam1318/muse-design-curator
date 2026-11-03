import type { BoardProfile } from '../api'

export const DOMAINS: { value: string; label: string }[] = [
  { value: 'watch', label: 'Watch' },
  { value: 'fashion', label: 'Fashion' },
  { value: 'interior', label: 'Interior' },
  { value: 'ui', label: 'UI' },
]

/** Share of the board a domain needs before Auto takes it (the backend's AUTO_MIN_SHARE). */
const AUTO_MIN_SHARE = 0.5

/** The domain most of the board's items vote for (what "Auto" currently means), else null. */
export function inferredDomain(profile: BoardProfile | undefined): string | null {
  const votes = profile?.domain_votes?.votes ?? {}
  const top = Object.entries(votes).sort((a, b) => b[1] - a[1])[0]
  return top && top[1] > AUTO_MIN_SHARE ? top[0] : null
}

export function toSnake(s: string): string {
  return s
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^[0-9_]+/, '')
    .replace(/_+$/g, '')
}
