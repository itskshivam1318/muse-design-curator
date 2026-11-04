import { act, cleanup, fireEvent, render } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { type PartConfirm, partConfirmStore, usePartConfirm } from '../shell/partConfirm'
import { PartConfirmLayer } from './PartConfirmLayer'

const item = { x: 0, y: 0, width: 200, height: 100 }

function Wrapper() {
  const c = usePartConfirm()
  return c ? <PartConfirmLayer confirm={c} screen={item} /> : null
}

const start = (over: Partial<PartConfirm> = {}) => {
  const answer = vi.fn()
  partConfirmStore.set({
    callId: 'c2',
    itemId: 'itm_7',
    maskUrl: '/api/media/masks/shade.png',
    box: [0.25, 0.125, 0.5, 0.5],
    mode: 'show',
    answer,
    ...over,
  })
  return answer
}

afterEach(() => {
  cleanup()
  partConfirmStore.set(null)
})

describe('PartConfirmLayer', () => {
  it('draws the mask tinted and the box outline over the item', () => {
    start()
    const { container } = render(<Wrapper />)
    expect(container.querySelector('image')?.getAttribute('href')).toContain('/api/media/masks/shade.png')
    expect(container.querySelector('feFlood')?.getAttribute('flood-opacity')).toBe('0.55')
    const box = container.querySelector<HTMLElement>('.part-confirm-box')!
    expect(box.style.left).toBe('50px')
    expect(box.style.top).toBe('12.5px')
    expect(box.style.width).toBe('50px')
    expect(box.style.height).toBe('37.5px')
    expect(container.querySelector('.part-confirm-draw')).toBeNull()
  })

  it('Fix then drag sends box fractions', () => {
    const answer = start({ mode: 'draw' })
    const { container } = render(<Wrapper />)
    const pad = container.querySelector('.part-confirm-draw')!
    fireEvent.pointerDown(pad, { button: 0, pointerId: 1, clientX: 20, clientY: 10 })
    fireEvent.pointerMove(pad, { pointerId: 1, clientX: 120, clientY: 60 })
    fireEvent.pointerUp(pad, { pointerId: 1, clientX: 120, clientY: 60 })
    expect(answer).toHaveBeenCalledTimes(1)
    const sent = answer.mock.calls[0][0]
    expect(sent.call_id).toBe('c2')
    expect(sent.box.map((v: number) => Number(v.toFixed(6)))).toEqual([0.1, 0.1, 0.6, 0.6])
  })

  it('a drag the other way round gives the same box', () => {
    const answer = start({ mode: 'draw' })
    const { container } = render(<Wrapper />)
    const pad = container.querySelector('.part-confirm-draw')!
    fireEvent.pointerDown(pad, { button: 0, pointerId: 1, clientX: 120, clientY: 60 })
    fireEvent.pointerUp(pad, { pointerId: 1, clientX: 20, clientY: 10 })
    expect(answer.mock.calls[0][0].box.map((v: number) => Number(v.toFixed(6)))).toEqual([0.1, 0.1, 0.6, 0.6])
  })

  it('a click without a drag sends nothing', () => {
    const answer = start({ mode: 'draw' })
    const { container } = render(<Wrapper />)
    const pad = container.querySelector('.part-confirm-draw')!
    fireEvent.pointerDown(pad, { button: 0, pointerId: 1, clientX: 50, clientY: 50 })
    fireEvent.pointerUp(pad, { pointerId: 1, clientX: 51, clientY: 50 })
    expect(answer).not.toHaveBeenCalled()
  })

  it('Esc leaves draw mode', () => {
    start({ mode: 'draw' })
    const { container } = render(<Wrapper />)
    act(() => {
      fireEvent.keyDown(window, { key: 'Escape' })
    })
    expect(partConfirmStore.get()?.mode).toBe('show')
    expect(container.querySelector('.part-confirm-draw')).toBeNull()
  })
})
