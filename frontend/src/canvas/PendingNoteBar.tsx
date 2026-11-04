/**
 * The bar over a written version of a note, waiting on the board: what it changed (the dimension
 * and the option's name), Keep (an ordinary note from then on) and ✕ (dismissed; ⌘Z brings it back).
 */
import type { ExploreOption } from '../api'
import type { Bounds } from './geometry'

interface Props {
  option: ExploreOption
  /** The explored dimension's label. */
  dimension: string
  /** The pending note's card in screen pixels; the bar sits on its top edge. */
  screen: Bounds
  readOnly: boolean
  busy: boolean
  onKeep: () => void
  onRemove: () => void
}

export function PendingNoteBar({ option, dimension, screen, readOnly, busy, onKeep, onRemove }: Props) {
  return (
    <div
      className="pending-note-bar"
      style={{ left: screen.x, top: screen.y, width: Math.max(screen.width, 260) }}
      onMouseDown={(e) => e.stopPropagation()}
      role="group"
      aria-label={`Written version: ${dimension}, ${option.name}`}
    >
      <span className="pending-note-tag" title={`${dimension}: ${option.description || option.name}`}>
        {option.name}
      </span>
      {!readOnly && (
        <>
          <button type="button" className="pending-note-keep" disabled={busy} onClick={onKeep}>
            Keep
          </button>
          <button type="button" className="pending-note-remove" disabled={busy} onClick={onRemove} aria-label="Remove this version">
            ✕
          </button>
        </>
      )}
    </div>
  )
}

/** Over a note while its versions are being written (under it sits the note's own bar). */
export function WritingChip({ count, screen }: { count: number; screen: Bounds }) {
  return (
    <div className="writing-chip" role="status" style={{ left: screen.x, top: screen.y - 8 }}>
      Writing {count} {count === 1 ? 'version' : 'versions'}…
    </div>
  )
}

/** A dimension's label from its key when the board's lens does not name it: `voice_authority` → `Voice authority`. */
export function keyLabel(key: string): string {
  const words = key.replace(/_/g, ' ').trim()
  return words.charAt(0).toUpperCase() + words.slice(1)
}
