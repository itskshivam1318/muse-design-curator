import { frameImageUrl } from '../api'
import { useFrames } from '../queries'
import type { Bounds } from './geometry'

interface Props {
  itemId: string
  screen: Bounds
  onChoose: (frameId: string) => void
  onEnter: () => void
  onLeave: () => void
  readOnly?: boolean
}

/** Key frames of a video item, under the image; click one to make it the item's picture. */
export function FramesStrip({ itemId, screen, onChoose, onEnter, onLeave, readOnly = false }: Props) {
  const { data: frames } = useFrames(itemId)
  if (!frames || frames.length < 2) return null
  return (
    <div
      className="frames-strip"
      role="group"
      aria-label="Video frames"
      style={{ left: screen.x, top: screen.y + screen.height + 8 }}
      onMouseEnter={onEnter}
      onMouseLeave={onLeave}
      onMouseDown={(e) => e.stopPropagation()}
    >
      {frames.map((f) => (
        <button
          key={f.id}
          type="button"
          aria-pressed={f.chosen}
          aria-label={`Use frame at ${(f.t_ms / 1000).toFixed(1)} s`}
          className={f.chosen ? 'frame is-chosen' : 'frame'}
          disabled={readOnly && !f.chosen}
          onClick={() => !f.chosen && onChoose(f.id)}
        >
          <img src={frameImageUrl(itemId, f.id)} alt="" loading="lazy" draggable={false} />
        </button>
      ))}
    </div>
  )
}
