import { type KeyboardEvent, useCallback, useEffect, useRef } from 'react'

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), summary, [tabindex]:not([tabindex="-1"])'

/**
 * Props for a non-native modal dialog: aria-modal, focus moved inside on open (to a
 * [data-autofocus] element, else the dialog itself), Tab / Shift+Tab trapped, Escape closes from
 * anywhere inside (inputs included) without reaching board shortcuts, and focus returns to
 * whatever had it before the dialog opened.
 */
export function useDialog<T extends HTMLElement>(onClose: () => void) {
  const ref = useRef<T>(null)
  const close = useRef(onClose)
  useEffect(() => {
    close.current = onClose
  })

  useEffect(() => {
    const before = document.activeElement as HTMLElement | null
    const el = ref.current
    const target = el?.querySelector<HTMLElement>('[data-autofocus]') ?? el
    target?.focus()
    return () => {
      // restore focus unless the user already moved it somewhere else on purpose
      const now = document.activeElement
      if (before && before.isConnected && (!now || now === document.body || el?.contains(now))) before.focus()
    }
  }, [])

  const onKeyDown = useCallback((e: KeyboardEvent<T>) => {
    if (e.key === 'Escape') {
      e.preventDefault()
      e.stopPropagation()
      e.nativeEvent.stopImmediatePropagation()
      close.current()
      return
    }
    if (e.key !== 'Tab' || !ref.current) return
    const items = [...ref.current.querySelectorAll<HTMLElement>(FOCUSABLE)].filter((n) => !n.closest('[hidden]'))
    if (items.length === 0) {
      e.preventDefault()
      return
    }
    const first = items[0]
    const last = items[items.length - 1]
    const active = document.activeElement
    if (e.shiftKey && (active === first || active === ref.current)) {
      e.preventDefault()
      last.focus()
    } else if (!e.shiftKey && active === last) {
      e.preventDefault()
      first.focus()
    }
  }, [])

  return { ref, role: 'dialog' as const, 'aria-modal': true, tabIndex: -1, onKeyDown }
}
