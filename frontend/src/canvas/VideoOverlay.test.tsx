import { cleanup, fireEvent, render } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { itemVideoUrl } from '../api'
import { makeItem } from '../test/fixtures'
import { VideoOverlay } from './VideoOverlay'

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})
const box = { x: 10, y: 20, width: 200, height: 120 }

describe('VideoOverlay', () => {
  it('plays muted and looping over the node, a second click stops it', () => {
    vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => {})
    const play = vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue()
    const onStop = vi.fn()
    const { container } = render(<VideoOverlay item={makeItem({ id: 'v', kind: 'video' })} screen={box} onStop={onStop} />)
    const video = container.querySelector('video')!
    expect(video.muted).toBe(true)
    expect(video.loop).toBe(true)
    // the exact route the backend serves (GET /api/items/{id}/video), with the item's cache token
    const item = makeItem({ id: 'v', kind: 'video' })
    expect(video.getAttribute('src')).toBe(itemVideoUrl(item))
    expect(video.getAttribute('src')).toMatch(/^\/api\/items\/v\/video\?v=[a-z0-9]*$/)
    expect(play).toHaveBeenCalled()
    expect((container.firstChild as HTMLElement).style.left).toBe('10px')
    fireEvent.click(video)
    expect(onStop).toHaveBeenCalledTimes(1)
  })
  it('Escape and a press outside stop it; a press inside does not', () => {
    vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => {})
    vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue()
    const onStop = vi.fn()
    const { container } = render(<VideoOverlay item={makeItem({ id: 'v', kind: 'video' })} screen={box} onStop={onStop} />)
    fireEvent.pointerDown(container.querySelector('video')!)
    expect(onStop).not.toHaveBeenCalled()
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(onStop).toHaveBeenCalledTimes(1)
    fireEvent.pointerDown(document.body)
    expect(onStop).toHaveBeenCalledTimes(2)
  })
})
