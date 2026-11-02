/**
 * The hovered part's region drawn over its item (HTML over the canvas, never hit-tested): a mask tinted
 * #ffd166 with a 2 px outline, a box, or (while a mask is being found) a dashed outline of its bbox.
 * A text range is not drawn here: the note highlights it itself (`NoteNode` `highlight`).
 */
import { useId } from 'react'
import { API_ORIGIN, type Item, type Region } from '../api'
import { type Bounds, toScreenBounds, type View } from '../canvas/geometry'
import { itemBounds } from '../canvas/nodeProps'
import { boxBounds, REGION_ALPHA, REGION_COLOR } from './regions'

const isBox = (b: readonly number[] | undefined | null): b is number[] => Array.isArray(b) && b.length === 4

/** Mask URLs come as `/api/media/…`: served from the API origin. */
const maskSrc = (url: string) => (/^https?:/.test(url) ? url : `${API_ORIGIN}${url}`)

interface Props {
  item: Item
  /** The part's region; while `loading`, only its `box` (if known) is used. */
  region: Region | null
  view: View
  /**
   * The region is still being found: a dashed outline of the bbox, or of the whole item. A mask
   * with no image (it could not be found) gets a solid outline of the same.
   */
  loading?: boolean
}

export function RegionOverlay({ item, region, view, loading = false }: Props) {
  const filterId = `region-${useId().replace(/:/g, '')}`
  if (!region || region.kind === 'text_range') return null
  const whole = itemBounds(item)
  const style = (b: Bounds) => {
    const s = toScreenBounds(b, view)
    return { left: s.x, top: s.y, width: s.width, height: s.height }
  }
  if (loading) {
    const b = isBox(region.box) ? boxBounds(whole, region.box) : whole
    return <div className="region-overlay is-loading" data-testid="region-overlay" data-state="loading" style={style(b)} aria-hidden="true" />
  }
  if (region.kind === 'box') {
    if (!isBox(region.box)) return null
    return <div className="region-overlay is-box" data-testid="region-overlay" data-state="box" style={style(boxBounds(whole, region.box))} aria-hidden="true" />
  }
  if (!region.mask_url) {
    const b = isBox(region.box) ? boxBounds(whole, region.box) : whole
    return <div className="region-overlay is-bbox" data-testid="region-overlay" data-state="bbox" style={style(b)} aria-hidden="true" />
  }
  const s = style(whole)
  // the mask (white on black) becomes alpha; a dilated copy minus the original is the outline
  return (
    <svg
      className="region-overlay is-mask"
      data-testid="region-overlay"
      data-state="mask"
      style={s}
      width={s.width}
      height={s.height}
      aria-hidden="true"
    >
      <defs>
        <filter id={filterId} x="0" y="0" width="1" height="1" colorInterpolationFilters="sRGB">
          <feColorMatrix in="SourceGraphic" type="luminanceToAlpha" result="part" />
          <feMorphology in="part" operator="dilate" radius="2" result="grown" />
          <feComposite in="grown" in2="part" operator="out" result="ring" />
          <feFlood floodColor={REGION_COLOR} result="ink" />
          <feComposite in="ink" in2="ring" operator="in" result="outline" />
          <feFlood floodColor={REGION_COLOR} floodOpacity={REGION_ALPHA} />
          <feComposite in2="part" operator="in" result="fill" />
          <feMerge>
            <feMergeNode in="fill" />
            <feMergeNode in="outline" />
          </feMerge>
        </filter>
      </defs>
      <image href={maskSrc(region.mask_url)} width={s.width} height={s.height} preserveAspectRatio="none" filter={`url(#${filterId})`} />
    </svg>
  )
}
