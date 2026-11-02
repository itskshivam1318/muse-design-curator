import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { makeItem } from '../test/fixtures'
import { RegionOverlay } from './RegionOverlay'
import { REGION_ALPHA, REGION_COLOR } from './regions'

afterEach(cleanup)

const item = makeItem({ id: 'i1', x: 100, y: 50, w: 400, h: 200 })
const view = { x: 10, y: 20, scale: 2 }
const box = () => screen.getByTestId('region-overlay')

describe('RegionOverlay', () => {
  it('a box part is a rect over its region, in screen space', () => {
    render(<RegionOverlay item={item} region={{ kind: 'box', box: [0.5, 0, 1, 0.5] }} view={view} />)
    expect(box().dataset.state).toBe('box')
    // canvas (300, 50, 200 x 100) at scale 2, offset (10, 20)
    expect(box().style.left).toBe('610px')
    expect(box().style.top).toBe('120px')
    expect(box().style.width).toBe('400px')
    expect(box().style.height).toBe('200px')
  })

  it('a mask is tinted #ffd166 at 0.35 with an outline, over the whole item', () => {
    render(<RegionOverlay item={item} region={{ kind: 'mask', box: [0, 0, 1, 1], mask_url: '/api/media/masks/m.png' }} view={view} />)
    expect(box().dataset.state).toBe('mask')
    expect(box().querySelector('image')!.getAttribute('href')).toContain('/api/media/masks/m.png')
    const floods = [...box().querySelectorAll('feFlood')]
    expect(floods.map((f) => f.getAttribute('flood-color'))).toEqual([REGION_COLOR, REGION_COLOR])
    expect(floods[1].getAttribute('flood-opacity')).toBe(String(REGION_ALPHA))
    expect(box().querySelector('feMorphology')!.getAttribute('radius')).toBe('2')
    expect(REGION_COLOR).toBe('#ffd166')
    expect(REGION_ALPHA).toBe(0.35)
  })

  it('loading: a dashed outline of the part bbox, or of the item when it has none', () => {
    const { rerender } = render(<RegionOverlay item={item} region={{ kind: 'mask', box: [0, 0, 0.5, 0.5] }} view={view} loading />)
    expect(box().dataset.state).toBe('loading')
    expect(box().style.width).toBe('400px')
    rerender(<RegionOverlay item={item} region={{ kind: 'mask' }} view={view} loading />)
    expect(box().style.width).toBe('800px')
  })

  it('a mask that could not be found: a solid outline of its bbox, or of the whole item', () => {
    const { rerender } = render(<RegionOverlay item={item} region={{ kind: 'mask', box: [0, 0, 0.5, 0.5] }} view={view} />)
    expect(box().dataset.state).toBe('bbox')
    expect(box().style.width).toBe('400px')
    rerender(<RegionOverlay item={item} region={{ kind: 'mask' }} view={view} />)
    expect(box().style.width).toBe('800px')
  })

  it('draws nothing for a text range (the note highlights it) or no region', () => {
    const { rerender } = render(<RegionOverlay item={item} region={{ kind: 'text_range', range: [0, 4] }} view={view} />)
    expect(screen.queryByTestId('region-overlay')).toBeNull()
    rerender(<RegionOverlay item={item} region={null} view={view} />)
    expect(screen.queryByTestId('region-overlay')).toBeNull()
  })
})
