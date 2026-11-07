/** A board image chosen for a slot (first/last frame): pick it, or drop an image item on it. Swap exchanges two linked slots. */
import { type DragEvent } from 'react'
import { type Item, itemImageUrl } from '../../api'
import { itemTitle } from '../../format'

interface Props {
  id: string
  label: string
  value: unknown
  /** The board's items by id. */
  items: ReadonlyMap<string, Item>
  readOnly?: boolean
  onSave: (v: unknown) => void
  /** Set when the slot has a linked one; exchanges the two values in one save. */
  onSwap?: () => void
}

export function FrameSlot({ id, label, value, items, readOnly, onSave, onSwap }: Props) {
  const images = [...items.values()].filter((i) => i.kind === 'image')
  const cur = typeof value === 'string' ? items.get(value) : undefined
  const onDrop = (e: DragEvent) => {
    e.preventDefault()
    if (readOnly) return
    const dropped = e.dataTransfer.getData('text/plain').trim()
    if (images.some((i) => i.id === dropped)) onSave(dropped)
  }
  return (
    <div className="node-frame" onDragOver={(e) => !readOnly && e.preventDefault()} onDrop={onDrop}>
      {cur?.thumb_path ? <img src={itemImageUrl(cur, 'thumb')} alt={itemTitle(cur)} /> : <span className="node-frame-empty">Drop an image</span>}
      <select id={id} aria-label={label} value={cur ? cur.id : ''} disabled={readOnly} onChange={(e) => onSave(e.target.value || undefined)}>
        <option value="">None</option>
        {images.map((i) => (
          <option key={i.id} value={i.id}>
            {itemTitle(i)}
          </option>
        ))}
      </select>
      {onSwap && (
        <button type="button" className="node-mini" disabled={readOnly} onClick={onSwap}>
          Swap
        </button>
      )}
    </div>
  )
}
