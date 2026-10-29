/** The small bar under a hovered or selected note: Visualize, and ⋯ for Edit, Send to node, Delete. */
import { useEffect, useRef, useState } from 'react'
import type { Item } from '../api'
import { LOCKED_TITLE, useDemo } from '../demo'
import { useNoteVisualizing } from '../events'
import { useBoardPlugins, usePlugins } from '../queries'
import type { Bounds } from './geometry'

interface Props {
  boardId: string
  note: Item
  /** The note's card in screen pixels; the bar hangs off its bottom-left edge. */
  screen: Bounds
  readOnly: boolean
  onVisualize: () => void
  onEdit: () => void
  onDelete: () => void
  /** Task 12 wires this to its node creation; the entries are hidden until it is passed. */
  onSendToNode?: (pluginId: string, noteId: string) => void
  onEnter?: () => void
  onLeave?: () => void
}

function Sparkle() {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.4" aria-hidden="true">
      <path d="M7 1.5l1.3 3.2 3.2 1.3-3.2 1.3L7 10.5 5.7 7.3 2.5 6l3.2-1.3z" />
    </svg>
  )
}

function Dots() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" aria-hidden="true">
      <path d="M3.5 8h.01M8 8h.01M12.5 8h.01" />
    </svg>
  )
}

/** Plugins added to the board that take notes as input. */
function useNotePlugins(boardId: string) {
  const { pluginsEnabled } = useDemo()
  const all = usePlugins().data
  const added = useBoardPlugins(boardId).data
  if (!pluginsEnabled || !all || !added) return []
  return all.filter((p) => added.includes(p.id) && p.inputs.kinds.includes('note'))
}

export function NoteBar({ boardId, note, screen, readOnly, onVisualize, onEdit, onDelete, onSendToNode, onEnter, onLeave }: Props) {
  const visualizing = useNoteVisualizing(note.id)
  const plugins = useNotePlugins(boardId)
  const [menuOpen, setMenuOpen] = useState(false)
  const more = useRef<HTMLButtonElement>(null)
  const menu = useRef<HTMLDivElement>(null)
  const empty = !(note.note_text ?? '').trim()

  useEffect(() => {
    if (menuOpen) menu.current?.querySelector<HTMLElement>('[role="menuitem"]')?.focus()
  }, [menuOpen])

  const close = (refocus: boolean) => {
    setMenuOpen(false)
    if (refocus) more.current?.focus()
  }
  const choose = (fn: () => void) => () => {
    setMenuOpen(false)
    fn()
  }

  return (
    <div
      className="note-bar"
      role="toolbar"
      aria-label="Note actions"
      style={{ left: screen.x + 8, top: screen.y + screen.height - 22 }}
      onMouseEnter={onEnter}
      onMouseLeave={onLeave}
    >
      <button
        type="button"
        className="note-bar-visualize"
        disabled={readOnly || empty || visualizing}
        title={readOnly ? LOCKED_TITLE : empty ? 'Write something to visualize' : undefined}
        aria-busy={visualizing || undefined}
        onClick={onVisualize}
      >
        <Sparkle />
        {visualizing ? 'Visualizing…' : 'Visualize'}
      </button>
      <button
        ref={more}
        type="button"
        className="note-bar-more"
        aria-label="More actions"
        aria-haspopup="menu"
        aria-expanded={menuOpen}
        onClick={() => setMenuOpen((o) => !o)}
      >
        <Dots />
      </button>
      {menuOpen && (
        <div
          ref={menu}
          className="note-bar-menu"
          role="menu"
          aria-label="Note"
          onKeyDown={(e) => {
            if (e.key === 'Escape') {
              e.stopPropagation()
              close(true)
            }
          }}
          onBlur={(e) => {
            const next = e.relatedTarget as Node | null
            if (next && !e.currentTarget.parentElement?.contains(next)) close(false)
          }}
        >
          <button type="button" role="menuitem" disabled={readOnly} onClick={choose(onEdit)}>
            Edit text
          </button>
          {onSendToNode && plugins.length > 0 && (
            <div role="group" aria-label="Send to node">
              <span className="note-bar-menu-label" aria-hidden="true">
                Send to node
              </span>
              {plugins.map((p) => (
                <button
                  key={p.id}
                  type="button"
                  role="menuitem"
                  disabled={readOnly}
                  onClick={choose(() => onSendToNode(p.id, note.id))}
                >
                  {p.name}
                </button>
              ))}
            </div>
          )}
          <button type="button" role="menuitem" className="is-danger" disabled={readOnly} onClick={choose(onDelete)}>
            Delete
          </button>
        </div>
      )}
    </div>
  )
}
