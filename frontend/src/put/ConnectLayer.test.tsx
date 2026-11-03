import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { type AnalysisView, type Item, keys, type PartView } from '../api'
import type { LivingWorld } from '../living/world'
import { LivingProvider } from '../living/useLiving'
import { itemBounds } from '../canvas/nodeProps'
import { makeItem } from '../test/fixtures'

vi.mock('../api', async (orig) => ({
  ...(await orig<typeof import('../api')>()),
  getRegion: vi.fn(() => new Promise(() => {})),
  getAnalysis: vi.fn(() => new Promise(() => {})),
  putInto: vi.fn(),
}))
const { getRegion, putInto } = await import('../api')
const { ghostStore, removeGhost } = await import('./ghosts')
const { ConnectLayer } = await import('./ConnectLayer')
const { putBodies } = await import('./bodies')
const { itemUnder, useConnect } = await import('./useConnect')

afterEach(() => {
  cleanup()
  ghostStore.get().ghosts.forEach((g) => removeGhost(g.jobId))
  vi.clearAllMocks()
})

const part = (over: Partial<PartView> & { key: string }): PartView => ({
  label: over.key, region_kind: 'mask', region: null, mask_url: null, source: 'ai', ...over,
})
const analysis: AnalysisView = {
  content_type: 'image',
  parse_status: 'completed',
  parts: [
    part({ key: 'front_wheel', label: 'Front wheel', region: [0.1, 0.6, 0.3, 0.9] }),
    part({ key: 'rear_wheel', label: 'Rear wheel', region: [0.7, 0.6, 0.9, 0.9] }),
    part({ key: 'car_body', label: 'Car body', region: [0, 0, 1, 1] }),
  ],
  dimensions: [],
}

// the source at (0,0) 200×200, the car to its right at (300,0) 400×200, a note under the source
const src = makeItem({ id: 'src', x: 0, y: 0, w: 200, h: 200, z: 1 })
const tgt = makeItem({ id: 'tgt', x: 300, y: 0, w: 400, h: 200, z: 2 })
const note = makeItem({ id: 'n', kind: 'note', note_text: 'hi', x: 0, y: 300, w: 200, h: 100, z: 3 })
const items = [src, tgt, note]

/** A world whose bodies sit where the items are stored. */
function fakeWorld(list: Item[], grabbing = false): LivingWorld {
  const byId = new Map(list.map((i) => [i.id, i]))
  return {
    body: (id: string) => {
      const i = byId.get(id)
      if (!i) return undefined
      const b = itemBounds(i)
      return { id, x: b.x + b.width / 2, y: b.y + b.height / 2, w: b.width, h: b.height, vx: 0, vy: 0 }
    },
    onFrame: () => () => {},
    grabbing: () => grabbing,
  } as unknown as LivingWorld
}

function setup(over: { selectedIds?: string[]; readOnly?: boolean; grabbing?: boolean; analysis?: AnalysisView } = {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })
  qc.setQueryData(keys.analysis('tgt'), over.analysis ?? analysis)
  const world = fakeWorld(items, over.grabbing)
  function Harness() {
    const connect = useConnect()
    const s = connect.state
    return (
      <>
        <ConnectLayer
          boardId="b1"
          items={items}
          view={{ x: 0, y: 0, scale: 1 }}
          world={world}
          readOnly={over.readOnly ?? false}
          selectedIds={over.selectedIds ?? ['src']}
          connect={connect}
        />
        <output data-testid="phase">{s.phase === 'idle' ? 'idle' : `${s.phase}:${s.targetId}:${s.spots.length}`}</output>
      </>
    )
  }
  render(
    <QueryClientProvider client={qc}>
      <LivingProvider world={world}>
        <Harness />
      </LivingProvider>
    </QueryClientProvider>,
  )
}

const dot = () => screen.queryByRole('button', { name: 'Connect to another picture' })
const phase = () => screen.getByTestId('phase').textContent
const line = () => document.querySelector('.put-line')

function dragTo(x: number, y: number) {
  const d = dot()!
  fireEvent.pointerDown(d, { button: 0, pointerId: 1, clientX: 200, clientY: 100 })
  fireEvent.pointerMove(d, { pointerId: 1, clientX: x, clientY: y })
  return d
}

describe('ConnectLayer', () => {
  it('shows the dot on the right edge of one selected image only', () => {
    setup()
    const d = dot()!
    expect(d).toBeTruthy()
    expect(d.style.left).toBe('200px')
    expect(d.style.top).toBe('100px')
    cleanup()
    setup({ selectedIds: ['n'] })
    expect(dot()).toBeNull()
    cleanup()
    setup({ selectedIds: ['src', 'tgt'] })
    expect(dot()).toBeNull()
    cleanup()
    setup({ readOnly: true })
    expect(dot()).toBeNull()
    cleanup()
    setup({ grabbing: true })
    expect(dot()).toBeNull()
  })

  it('aims at the front wheel and its kind; letting go opens the card phase with 2 spots', () => {
    setup()
    // the front wheel: fx 0.2, fy 0.75 of the car
    const d = dragTo(380, 150)
    expect(line()).toBeTruthy()
    expect(screen.getAllByTestId('region-overlay')).toHaveLength(2)
    expect(screen.getByText('2 spots')).toBeTruthy()
    expect(getRegion).toHaveBeenCalledWith('tgt', 'front_wheel')
    expect(getRegion).toHaveBeenCalledWith('tgt', 'rear_wheel')
    expect(phase()).toBe('drag:tgt:2')
    fireEvent.pointerUp(d, { pointerId: 1, clientX: 380, clientY: 150 })
    expect(phase()).toBe('card:tgt:2')
  })

  it('over the car body alone: 1 spot', () => {
    setup()
    dragTo(500, 50)
    expect(screen.getByText('1 spot')).toBeTruthy()
    expect(screen.getAllByTestId('region-overlay')).toHaveLength(1)
  })

  it('over no part: one spot "here", marked by a ring', () => {
    setup({ analysis: { ...analysis, parts: analysis.parts.slice(0, 2) } })
    dragTo(500, 50)
    expect(screen.getByText('1 spot')).toBeTruthy()
    expect(screen.queryAllByTestId('region-overlay')).toHaveLength(0)
    const ring = document.querySelector<HTMLElement>('.put-ring')!
    expect(ring.style.left).toBe('500px')
    expect(ring.style.top).toBe('50px')
    fireEvent.pointerUp(dot()!, { pointerId: 1, clientX: 500, clientY: 50 })
    expect(phase()).toBe('card:tgt:1')
  })

  it.each([
    ['the source itself', 100, 100],
    ['a note', 100, 350],
    ['empty board', 900, 900],
  ])('letting go over %s goes back to idle, leaving no line', (_name, x, y) => {
    setup()
    const d = dragTo(x, y)
    expect(line()).toBeTruthy()
    expect(screen.queryAllByTestId('region-overlay')).toHaveLength(0)
    expect(phase()).toBe('drag:null:0')
    fireEvent.pointerUp(d, { pointerId: 1, clientX: x, clientY: y })
    expect(phase()).toBe('idle')
    expect(line()).toBeNull()
  })

  it('the card: Put in sends the spots left on and the words, adds a ghost, and closes the line and card', async () => {
    vi.mocked(putInto).mockResolvedValue({ job_id: 'j1', x: 760, y: 0, w: 400, h: 200 })
    setup()
    const d = dragTo(380, 150)
    fireEvent.pointerUp(d, { pointerId: 1, clientX: 380, clientY: 150 })
    expect(screen.getByRole('dialog')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: '✓ Rear wheel' }))
    fireEvent.change(screen.getByPlaceholderText('Anything to add? (optional)'), { target: { value: '  keep the blur ' } })
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Put in' }))
    })
    expect(putInto).toHaveBeenCalledWith('tgt', { source_id: 'src', spots: [{ part: 'front_wheel' }], words: 'keep the blur' })
    expect(ghostStore.get().ghosts).toEqual([
      {
        jobId: 'j1', boardId: 'b1', targetId: 'tgt', x: 760, y: 0, w: 400, h: 200, error: null,
        request: { targetId: 'tgt', body: { source_id: 'src', spots: [{ part: 'front_wheel' }], words: 'keep the blur' } },
      },
    ])
    expect(phase()).toBe('idle')
    expect(line()).toBeNull()
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(screen.getByText('Putting in…')).toBeTruthy()
  })

  it('the card: a refused Put in keeps the card open with the message; Cancel closes it', async () => {
    vi.mocked(putInto).mockRejectedValue(new Error('Daily limit reached'))
    setup()
    const d = dragTo(380, 150)
    fireEvent.pointerUp(d, { pointerId: 1, clientX: 380, clientY: 150 })
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Put in' }))
    })
    expect(putInto).toHaveBeenCalledWith('tgt', { source_id: 'src', spots: [{ part: 'front_wheel' }, { part: 'rear_wheel' }] })
    expect(screen.getByRole('alert').textContent).toBe('Daily limit reached')
    expect(phase()).toBe('card:tgt:2')
    expect(ghostStore.get().ghosts).toHaveLength(0)
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(phase()).toBe('idle')
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('Esc during a drag cancels it', () => {
    setup()
    dragTo(380, 150)
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(phase()).toBe('idle')
    expect(line()).toBeNull()
    expect(screen.queryAllByTestId('region-overlay')).toHaveLength(0)
  })
})

describe('putBodies', () => {
  it('the open card is an obstacle its screen size at the zoom, each ghost an item at its centre', () => {
    const g = { jobId: 'j1', boardId: 'b1', targetId: 'tgt', x: 760, y: 0, w: 400, h: 200, error: null,
      request: { targetId: 'tgt', body: { source_id: 'src', spots: [] } } }
    expect(putBodies({ x: 450, y: 125 }, [g], 2)).toEqual([
      { id: 'put-card', kind: 'obstacle', w: 130, h: 85, home: { kind: 'abs', x: 450, y: 125 } },
      { id: 'ghost:j1', kind: 'item', w: 400, h: 200, home: { kind: 'abs', x: 960, y: 100 } },
    ])
    expect(putBodies(null, [], 1)).toEqual([])
  })
})

describe('itemUnder', () => {
  const bounds = (list: Item[]) => (id: string) => {
    const i = list.find((x) => x.id === id)
    return i ? itemBounds(i) : null
  }
  it('picks the higher z of two overlapping images and skips staged ones', () => {
    const low = makeItem({ id: 'low', x: 0, y: 0, w: 100, h: 100, z: 1 })
    const high = makeItem({ id: 'high', x: 50, y: 50, w: 100, h: 100, z: 5 })
    const staged = makeItem({ id: 'staged', x: 50, y: 50, w: 100, h: 100, z: 9, staged: true })
    const list = [low, high, staged]
    expect(itemUnder(list, bounds(list), { x: 75, y: 75 }, 'x')?.id).toBe('high')
    expect(itemUnder(list, bounds(list), { x: 25, y: 25 }, 'x')?.id).toBe('low')
    expect(itemUnder(list, bounds(list), { x: 75, y: 75 }, 'high')?.id).toBe('low')
    expect(itemUnder(list, bounds(list), { x: 500, y: 500 }, 'x')).toBeNull()
  })
  it('never counts notes, links or videos', () => {
    const list = (['note', 'link', 'video'] as const).map((kind, i) => makeItem({ id: kind, kind, x: 0, y: 0, w: 100, h: 100, z: i }))
    expect(itemUnder(list, bounds(list), { x: 50, y: 50 }, 'x')).toBeNull()
  })
})
