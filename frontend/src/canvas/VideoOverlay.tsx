import { useEffect, useRef } from 'react'
import { type Item, itemImageUrl, itemVideoUrl } from '../api'
import type { Bounds } from './geometry'

interface Props {
  item: Item
  /** The video item's box on screen: the player sits exactly over it, so it follows pan and zoom. */
  screen: Bounds
  onStop: () => void
}

/** Inline playback over a video item on the canvas: muted, looping; click, Escape or a press outside stops it. */
export function VideoOverlay({ item, screen, onStop }: Props) {
  const box = useRef<HTMLDivElement>(null)
  const video = useRef<HTMLVideoElement>(null)
  const stop = useRef(onStop)
  useEffect(() => {
    stop.current = onStop
  })
  useEffect(() => {
    void video.current?.play()?.catch(() => {}) // autoplay may be refused; the poster stays
    const key = (e: KeyboardEvent) => {
      if (e.key === 'Escape') stop.current()
    }
    const press = (e: Event) => {
      if (!box.current?.contains(e.target as Node)) stop.current()
    }
    window.addEventListener('keydown', key)
    document.addEventListener('pointerdown', press)
    const el = video.current
    return () => {
      window.removeEventListener('keydown', key)
      document.removeEventListener('pointerdown', press)
      el?.pause()
    }
  }, [])
  return (
    <div ref={box} className="video-overlay" style={{ left: screen.x, top: screen.y, width: screen.width, height: screen.height }}>
      <video
        ref={video}
        src={itemVideoUrl(item)}
        poster={itemImageUrl(item, 'thumb')}
        muted
        loop
        playsInline
        aria-label="Video playing; click to pause"
        onClick={onStop}
      />
    </div>
  )
}
