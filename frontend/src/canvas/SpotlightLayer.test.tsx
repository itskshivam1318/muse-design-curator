import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import type { AgentStep } from '../api'
import { closeSpotlight, spotlightStore, startSpotlight, useSpotlight } from '../shell/spotlight'
import type { Bounds } from './geometry'
import { SpotlightLayer } from './SpotlightLayer'

const step = (turn: number, say: string | null): AgentStep => ({
  id: `s${turn}`,
  run_id: 'r1',
  turn,
  tool: 'render_image',
  args: {},
  say,
  ok: true,
  result: {},
  item_ids: [],
  highlight: true,
  created_at: '2026-11-04T00:00:00Z',
})
const b = (x: number, y: number): Bounds => ({ x, y, width: 100, height: 80 })
const size = { width: 1000, height: 700 }

function Wrapper({ lit = [b(10, 10)] }: { lit?: Bounds[] }) {
  const s = useSpotlight()
  return s ? <SpotlightLayer spotlight={s} lit={lit} size={size} /> : null
}

beforeEach(() => {
  startSpotlight('r1', [step(12, 'Rendering the anchor room.'), step(15, 'Placing the lamp.')])
})
afterEach(() => {
  cleanup()
  closeSpotlight()
})

describe('SpotlightLayer', () => {
  it('cuts out every present item', () => {
    const { container } = render(<Wrapper lit={[b(10, 10), b(200, 10), b(400, 10)]} />)
    const d = container.querySelector('path.spotlight-dim')!.getAttribute('d')!
    expect(d.match(/M/g)).toHaveLength(4)
    expect(container.querySelector('path.spotlight-dim')!.getAttribute('fill-rule')).toBe('evenodd')
  })

  it("shows the card centred when the step's items are gone", () => {
    render(<Wrapper lit={[]} />)
    expect(screen.getByText("This step's pictures are no longer on the board.")).toBeTruthy()
  })

  it('shows the say, the step number and the count; Back is off on the first', () => {
    render(<Wrapper />)
    expect(screen.getByText('Rendering the anchor room.')).toBeTruthy()
    expect(screen.getByText('Step 12')).toBeTruthy()
    expect(screen.getByText('1 of 2')).toBeTruthy()
    expect((screen.getByRole('button', { name: 'Back' }) as HTMLButtonElement).disabled).toBe(true)
    expect(screen.getByRole('dialog', { name: 'Replay' })).toBeTruthy()
  })

  it('falls back to the tool name when there is no say', () => {
    closeSpotlight()
    startSpotlight('r1', [step(3, null)])
    render(<Wrapper />)
    expect(screen.getByText('render_image')).toBeTruthy()
  })

  it('moves focus to Next on mount', () => {
    render(<Wrapper />)
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Next' }))
  })

  it('Escape closes only the replay', () => {
    render(<Wrapper />)
    const other = vi.fn()
    window.addEventListener('keydown', other)
    fireEvent.keyDown(window, { key: 'Escape' })
    window.removeEventListener('keydown', other)
    expect(spotlightStore.get()).toBeNull()
    expect(other).not.toHaveBeenCalled()
  })

  it('arrow keys step', () => {
    render(<Wrapper />)
    fireEvent.keyDown(window, { key: 'ArrowRight' })
    expect(spotlightStore.get()!.index).toBe(1)
    fireEvent.keyDown(window, { key: 'ArrowLeft' })
    expect(spotlightStore.get()!.index).toBe(0)
  })

  it('keys typed in an input are left alone', () => {
    render(
      <>
        <input aria-label="note" />
        <Wrapper />
      </>,
    )
    const input = screen.getByLabelText('note')
    input.focus()
    fireEvent.keyDown(input, { key: 'ArrowRight' })
    expect(spotlightStore.get()!.index).toBe(0)
  })

  it('says Done on the last step and closes', () => {
    render(<Wrapper />)
    fireEvent.click(screen.getByRole('button', { name: 'Next' }))
    fireEvent.click(screen.getByRole('button', { name: 'Done' }))
    expect(spotlightStore.get()).toBeNull()
  })

  it('the close button closes', () => {
    render(<Wrapper />)
    fireEvent.click(screen.getByRole('button', { name: 'Close replay' }))
    expect(spotlightStore.get()).toBeNull()
  })

  it('stops listening for keys when it unmounts', () => {
    const { unmount } = render(<Wrapper />)
    unmount()
    fireEvent.keyDown(window, { key: 'ArrowRight' })
    expect(spotlightStore.get()!.index).toBe(0)
  })
})
