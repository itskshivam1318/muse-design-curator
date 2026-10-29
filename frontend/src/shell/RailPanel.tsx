import { type ReactNode, useEffect, useRef } from 'react'
import { type Item, itemImageUrl } from '../api'
import { useSelection } from '../canvas/selection'
import { itemTitle } from '../format'
import { PluginsPanel } from '../plugins/PluginsPanel'
import { visibleItems } from '../queries'
import { RAIL_LABELS, type RailId } from './tools'

interface Props {
  id: RailId
  boardId: string
  items: Item[]
  onClose: () => void
  /** Library: an item was picked; select it and bring it into view. */
  onFocusItem: (item: Item) => void
  /** Search: open Find real examples for this image. */
  onFindExamples: (item: Item) => void
  /** Library extras under the items list: add actions, board signals, lens review. */
  library?: ReactNode
}

const label = (item: Item) => (item.kind === 'note' ? item.note_text?.trim() || 'Note' : itemTitle(item))

function Thumb({ item }: { item: Item }) {
  if ((item.kind === 'image' || item.kind === 'video') && item.thumb_path)
    return <img className="lib-thumb" src={itemImageUrl(item, 'thumb')} alt="" loading="lazy" />
  return <span className={`lib-thumb is-${item.kind}`} aria-hidden="true" />
}

function ItemList({ items, name, onPick }: { items: Item[]; name: string; onPick: (item: Item) => void }) {
  const { selected } = useSelection()
  return (
    <ul className="lib-list" aria-label={name}>
      {items.map((item) => (
        <li key={item.id}>
          <button
            type="button"
            className={selected.includes(item.id) ? 'lib-row is-selected' : 'lib-row'}
            onClick={() => onPick(item)}
          >
            <Thumb item={item} />
            <span className="lib-label">{label(item)}</span>
          </button>
        </li>
      ))}
    </ul>
  )
}

/** The slide-out beside the rail, over the canvas. Esc (or the rail icon again) closes it. */
export function RailPanel({ id, boardId, items, onClose, onFocusItem, onFindExamples, library }: Props) {
  const ref = useRef<HTMLElement>(null)
  // opened from its rail button: take focus; opened by the board (a lens to review): leave focus be
  useEffect(() => {
    if (document.activeElement?.closest('.left-rail')) ref.current?.focus()
  }, [id])
  const visible = visibleItems(items)
  const images = visible.filter((i) => i.kind === 'image')
  const name = RAIL_LABELS[id]
  return (
    <section
      ref={ref}
      className="rail-panel"
      role="dialog"
      aria-label={name}
      tabIndex={-1}
      onKeyDown={(e) => {
        if (e.key !== 'Escape') return
        e.stopPropagation() // innermost first: the board's Escape chain must not also run
        onClose()
      }}
    >
      <div className="rail-panel-head">
        <h2>{name}</h2>
        <button type="button" className="icon-btn" aria-label={`Close ${name}`} onClick={onClose}>
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
            <path d="M3 3l8 8M11 3l-8 8" />
          </svg>
        </button>
      </div>
      {id === 'library' && (
        <>
          {visible.length > 0 ? (
            <ItemList items={visible} name="Items on this board" onPick={onFocusItem} />
          ) : (
            <p className="muted small">Nothing on this board yet.</p>
          )}
          {library}
        </>
      )}
      {id === 'search' &&
        (images.length > 0 ? (
          <>
            <h3 className="rail-sub">Find real examples of</h3>
            <ItemList items={images} name="Find real examples of" onPick={onFindExamples} />
          </>
        ) : (
          <p className="muted small">Add an image to find real examples of it.</p>
        ))}
      {id === 'plugins' && <PluginsPanel boardId={boardId} />}
      {id === 'vocabulary' && <p className="muted">Vocabulary is coming soon.</p>}
    </section>
  )
}
