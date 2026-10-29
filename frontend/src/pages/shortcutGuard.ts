/** Board shortcuts (v, i, x, f, Delete, n, a) must not fire while focus is inside an open dialog or drawer. */
const OVERLAY = '[role="dialog"], [aria-modal="true"], .right-drawer'

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
