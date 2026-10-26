import { describe, expect, it, vi } from 'vitest'
import { handleDrop } from './drop'
import { toCanvasPoint, zoomAt } from './geometry'

describe('drop', () => {
  it('drop places item at pointer in canvas coords under zoom', () => {
    const upload = vi.fn()
    const file = new File(['x'], 'a.png', { type: 'image/png' })
    handleDrop(
      {
        clientX: 340, clientY: 270,
        containerRect: { left: 40, top: 20 },
        view: { x: 100, y: 50, scale: 2 },
        files: [file],
      },
      upload,
    )
    // pointer in container = (300, 250); canvas = (pointer − stage) / scale = (100, 100)
    expect(upload).toHaveBeenCalledWith([file], { x: 100, y: 100 }, 'drop')
  })

  it('ignores drops without files', () => {
    const upload = vi.fn()
    handleDrop(
      { clientX: 0, clientY: 0, containerRect: { left: 0, top: 0 }, view: { x: 0, y: 0, scale: 1 }, files: [] },
      upload,
    )
    expect(upload).not.toHaveBeenCalled()
  })
})

describe('geometry', () => {
  it('zoomAt keeps the point under the pointer fixed and clamps 10%-400%', () => {
    const view = { x: 10, y: 20, scale: 1 }
    const pointer = { x: 200, y: 100 }
    const before = toCanvasPoint(pointer, view)
    const next = zoomAt(view, pointer, 2)
    expect(toCanvasPoint(pointer, next)).toEqual(before)
    expect(zoomAt(view, pointer, 99).scale).toBe(4)
    expect(zoomAt(view, pointer, 0.001).scale).toBe(0.1)
  })
})
