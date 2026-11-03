import { useEffect, useRef, useState } from 'react'
import { LOCKED_TITLE } from '../demo'
import { AddActions } from './AddMenu'

interface Props {
  onFiles: (files: File[]) => void
  onLink: (url: string) => Promise<unknown>
  /** Public demo, not unlocked: nothing can be added. */
  disabled?: boolean
}

/** Floating + beside the tool dock: opens the add actions (upload, link, extension) in a popover. */
export function AddFab({ onFiles, onLink, disabled = false }: Props) {
  const [open, setOpen] = useState(false)
  const root = useRef<HTMLDivElement>(null)
  const button = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return
      setOpen(false)
      button.current?.focus()
    }
    const onDown = (e: MouseEvent) => {
      if (!root.current?.contains(e.target as Node)) setOpen(false)
    }
    window.addEventListener('keydown', onKey)
    document.addEventListener('mousedown', onDown)
    return () => {
      window.removeEventListener('keydown', onKey)
      document.removeEventListener('mousedown', onDown)
    }
  }, [open])

  const shown = open && !disabled
  const pop = useRef<HTMLDivElement>(null)

  // a dialog takes focus: its first action, so the keyboard starts inside it
  useEffect(() => {
    if (shown) pop.current?.querySelector<HTMLElement>('button:not([disabled])')?.focus()
  }, [shown])

  return (
    <div className="add-fab-wrap" ref={root}>
      {shown && (
        <div ref={pop} className="add-fab-pop" role="dialog" aria-label="Add to board">
          <AddActions
            onFiles={(files) => {
              setOpen(false)
              onFiles(files)
            }}
            onLink={async (url) => {
              const r = await onLink(url)
              setOpen(false)
              return r
            }}
          />
        </div>
      )}
      <button
        ref={button}
        type="button"
        className="add-fab"
        aria-label="Add to board"
        aria-haspopup="dialog"
        aria-expanded={shown}
        disabled={disabled}
        title={disabled ? LOCKED_TITLE : undefined}
        onClick={() => setOpen((o) => !o)}
      >
        <span className="add-fab-plus" aria-hidden="true">+</span>
      </button>
    </div>
  )
}
