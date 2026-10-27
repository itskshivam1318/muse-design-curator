/** Board shortcuts (v, i, x, f, Delete) must not fire while focus is inside an open dialog or drawer. */
const OVERLAY = '[role="dialog"], [aria-modal="true"], .right-drawer'

export function insideOverlay(t: EventTarget | null): boolean {
  const el = t as HTMLElement | null
  return !!el && typeof el.closest === 'function' && el.closest(OVERLAY) !== null
}
