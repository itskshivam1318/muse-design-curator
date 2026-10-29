import type { Item } from '../api'

/**
 * Board shortcuts (v, i, x, f, Delete, n, a) must not fire while focus is inside an open dialog or
 * drawer, or on a plugin node card's controls (Backspace on its Run button is not "delete items").
 */
const OVERLAY = '[role="dialog"], [aria-modal="true"], .right-drawer, .node-card'

export function insideOverlay(t: EventTarget | null): boolean {
  const el = t as HTMLElement | null
  return !!el && typeof el.closest === 'function' && el.closest(OVERLAY) !== null
}

/** No shortcut fires while the person types: inputs, textareas, selects and contenteditable. */
export function isTyping(t: EventTarget | null): boolean {
  const el = t as HTMLElement | null
  if (!el || !el.tagName) return false
  return el.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName)
}

/** Whether a keydown may switch board tools: not while typing, not with modifiers, not inside an overlay (Escape excepted). */
export function toolShortcutAllowed(e: KeyboardEvent): boolean {
  if (isTyping(e.target)) return false
  if (e.metaKey || e.ctrlKey || e.altKey) return false
  return e.key === 'Escape' || !insideOverlay(e.target)
}

export type ItemShortcut =
  | { kind: 'panel'; panel: 'explore' | 'vary' | 'inspect'; itemId: string }
  | { kind: 'notThis'; items: Item[] }
  | null

/**
 * What `v`, `i` and `x` do with the selection. They are image shortcuts: notes in the selection are
 * left out, and with nothing else selected the key does nothing.
 */
export function itemShortcut(key: string, chosen: readonly Item[], flags: { explore: boolean; locked: boolean }): ItemShortcut {
  const targets = chosen.filter((i) => i.kind !== 'note')
  switch (key.toLowerCase()) {
    case 'v':
      return targets.length === 1 ? { kind: 'panel', panel: flags.explore ? 'explore' : 'vary', itemId: targets[0].id } : null
    case 'i':
      return targets.length === 1 ? { kind: 'panel', panel: 'inspect', itemId: targets[0].id } : null
    case 'x':
      return !flags.locked && targets.length > 0 ? { kind: 'notThis', items: targets } : null
    default:
      return null
  }
}
