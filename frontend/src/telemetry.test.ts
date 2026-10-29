import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { describeUiAction, flush, setBoard, track, uiActivity } from './telemetry'

describe('telemetry', () => {
  const fetchMock = vi.fn(() => Promise.resolve(new Response(null, { status: 204 })))
  beforeEach(() => {
    vi.useFakeTimers()
    vi.stubGlobal('fetch', fetchMock)
    fetchMock.mockClear()
  })
  afterEach(() => {
    setBoard(null)
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  const bodies = () => fetchMock.mock.calls.map((c) => JSON.parse((c as unknown as [string, RequestInit])[1].body as string))

  it('drops events when no board is open', () => {
    track('drawer.open')
    flush()
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('batches events and posts them to the board after a short delay', () => {
    setBoard('brd_1')
    track('drawer.open', { itemId: 'itm_1', detail: { kind: 'vary' } })
    track('vary.run', { itemId: 'itm_1', runId: 'run_1' })
    expect(fetchMock).not.toHaveBeenCalled()
    vi.advanceTimersByTime(2000)
    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toMatch(/\/api\/boards\/brd_1\/ui-events$/)
    expect(init.keepalive).toBe(true)
    const { events } = bodies()[0]
    expect(events.map((e: { action: string }) => e.action)).toEqual(['drawer.open', 'vary.run'])
    expect(events[0]).toMatchObject({ item_id: 'itm_1', detail: { kind: 'vary' } })
    expect(events[1]).toMatchObject({ run_id: 'run_1' })
    expect(typeof events[0].at).toBe('string')
  })

  it('switching boards sends the old board its events first', () => {
    setBoard('brd_a')
    track('candidate.open')
    setBoard('brd_b')
    const [url] = fetchMock.mock.calls[0] as unknown as [string]
    expect(url).toMatch(/brd_a/)
  })

  it('splits large queues into batches the server accepts', () => {
    setBoard('brd_1')
    for (let i = 0; i < 120; i++) track('x')
    flush()
    expect(bodies().map((b) => b.events.length)).toEqual([50, 50, 20])
  })

  it('a failing network never throws', () => {
    fetchMock.mockImplementationOnce(() => Promise.reject(new Error('offline')))
    setBoard('brd_1')
    track('x')
    expect(() => flush()).not.toThrow()
  })
})

describe('ui activity', () => {
  afterEach(() => setBoard(null))

  it('keeps a plain sentence for the actions worth showing, and skips the rest', () => {
    setBoard('brd_1')
    track('drawer.open', { itemId: 'i1', detail: { kind: 'inspect' } })
    track('drawer.close', { itemId: 'i1', detail: { kind: 'inspect' } })
    track('candidate.open', { detail: { candidate: 'c1' } })
    track('vary.run', { itemId: 'i1', runId: 'r1', detail: { target: 'dial_color' } })
    track('candidate.keep', { runId: 'r1' })
    track('candidate.reject', { runId: 'r1' })
    track('item.remove', { detail: { items: ['a', 'b'] } })
    track('item.role', { detail: { items: ['a'], role: 'counter_example' } })
    track('something.new')
    expect(uiActivity.get().map((e) => e.text)).toEqual([
      'Opened Inspect.',
      'Started Find real examples for dial color.',
      'Kept a real example.',
      'Rejected a real example.',
      'Removed 2 items.',
      'Marked 1 item as not this.',
    ])
  })

  it('keeps the last 50 and clears when the board changes', () => {
    setBoard('brd_1')
    for (let i = 0; i < 60; i++) track('item.remove', { detail: { items: ['a'] } })
    expect(uiActivity.get()).toHaveLength(50)
    setBoard('brd_2')
    expect(uiActivity.get()).toHaveLength(0)
  })

  it('describeUiAction returns null for unknown actions', () => {
    expect(describeUiAction('run.shown', {})).toBeNull()
    expect(describeUiAction('nope', undefined)).toBeNull()
  })
})
