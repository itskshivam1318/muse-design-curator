import { cleanup, render } from '@testing-library/react'
import { act } from 'react'
import { useRef } from 'react'
import { afterEach, describe, expect, it } from 'vitest'
import { LivingProvider, useBodyElement, useLivingWorld } from './useLiving'
import { createLivingWorld } from './world'
import type { Scene } from './scene'

const scene = (id: string): Scene => ({
  specs: [{ id, kind: 'item', w: 100, h: 80, home: { kind: 'abs', x: 200, y: 100 } }],
  edges: [], flowers: [], docked: new Map(),
})

function Box({ id }: { id: string }) {
  const ref = useRef<HTMLDivElement>(null)
  useBodyElement(id, ref)
  return <div ref={ref} data-testid="box" />
}

function setup() {
  let t = 0
  let cb: FrameRequestCallback | null = null
  const world = createLivingWorld({ reduced: true, now: () => t, schedule: (f) => ((cb = f), 1), cancel: () => {} })
  const frame = (): void => {
    t += 1000
    act(() => cb?.(t))
  }
  return { world, frame, advance: () => (t += 1000) }
}

afterEach(cleanup)

describe('useBodyElement', () => {
  it('writes transform, size and opacity each frame', () => {
    const { world, frame } = setup()
    world.sync(scene('a'), 0)
    const { getByTestId } = render(<LivingProvider world={world}><Box id="a" /></LivingProvider>)
    world.start()
    frame()
    const el = getByTestId('box')
    expect(el.style.width).toBe('100px')
    expect(el.style.height).toBe('80px')
    expect(el.style.transform).toContain('translate(150px, 60px)')
    expect(el.style.opacity).toBe('1')
  })

  it('hides the element when the body is missing', () => {
    const { world, frame } = setup()
    const { getByTestId } = render(<LivingProvider world={world}><Box id="nope" /></LivingProvider>)
    world.start()
    frame()
    expect(getByTestId('box').style.opacity).toBe('0')
  })

  it('useLivingWorld throws without a provider', () => {
    function Bad() {
      useLivingWorld()
      return null
    }
    const err = console.error
    console.error = () => {}
    expect(() => render(<Bad />)).toThrow()
    console.error = err
  })
})
