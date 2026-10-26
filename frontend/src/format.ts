import type { Item } from './api'

/** "brushed_steel" → "Brushed steel" */
export function humanize(token: string | null | undefined): string {
  if (token === null || token === undefined || token === '') return 'Unknown'
  const s = String(token).replace(/_/g, ' ').trim()
  return s.charAt(0).toUpperCase() + s.slice(1)
}

/** "123456" → "123 456" */
export function formatPairCode(code: string): string {
  return code.length === 6 ? `${code.slice(0, 3)} ${code.slice(3)}` : code
}

export function hostOf(url: string | null | undefined): string | null {
  if (!url) return null
  try {
    return new URL(url).hostname.replace(/^www\./, '')
  } catch {
    return null
  }
}

/** A short human title for an item. */
export function itemTitle(item: Item): string {
  return item.page_title || item.original_filename || item.creator_handle || `${item.kind} item`
}

/**
 * An absolute http(s) URL that is safe to put in an href, else null. Anything else (javascript:,
 * data:, relative or malformed) is dropped, so the link is not rendered at all.
 */
export function safeExternalUrl(u: string | null | undefined): string | null {
  if (!u) return null
  const s = u.trim()
  try {
    const { protocol } = new URL(s)
    return protocol === 'http:' || protocol === 'https:' ? s : null
  } catch {
    return null
  }
}
