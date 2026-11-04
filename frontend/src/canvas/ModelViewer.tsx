import { createElement, useEffect, useState } from 'react'
import { type Item, itemImageUrl, itemModelUrl } from '../api'

interface Props {
  item: Item
  onClose: () => void
}

/** A 3D item in an overlay: orbit and zoom, plus the .glb to download. The viewer library loads on first open. */
export function ModelViewer({ item, onClose }: Props) {
  const [ready, setReady] = useState(false)
  const [failed, setFailed] = useState(false)
  useEffect(() => {
    let live = true
    import('@google/model-viewer').then(
      () => live && setReady(true),
      () => live && setFailed(true),
    )
    return () => {
      live = false
    }
  }, [])
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', key)
    return () => window.removeEventListener('keydown', key)
  }, [onClose])
  const src = itemModelUrl(item)
  const name = item.original_filename?.endsWith('.glb') ? item.original_filename : `${item.original_filename ?? 'model'}.glb`
  return (
    <div className="model-overlay" role="dialog" aria-label="3D viewer" onMouseDown={(e) => e.stopPropagation()}>
      <div className="model-overlay-bar">
        <a href={src} download={name}>
          Download .glb
        </a>
        <button type="button" onClick={onClose}>
          Close
        </button>
      </div>
      {ready &&
        createElement('model-viewer', {
          src,
          poster: itemImageUrl(item, 'thumb'),
          alt: item.original_filename ?? '3D model',
          'camera-controls': '',
          'auto-rotate': '',
          'shadow-intensity': '1',
          class: 'model-overlay-view',
        })}
      {!ready && <p className="model-overlay-note">{failed ? 'The 3D viewer could not load.' : 'Loading the 3D viewer…'}</p>}
    </div>
  )
}
