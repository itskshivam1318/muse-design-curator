import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, renderHook } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { keys } from '../api'
import { exp, opt } from '../test/explore'
import { makeItem } from '../test/fixtures'
import type { ReleasePlan } from '../living/release'

vi.mock('../api', async (orig) => ({
  ...(await orig<typeof import('../api')>()),
  patchItem: vi.fn(() => Promise.resolve()),
  patchExploration: vi.fn(() => Promise.resolve()),
  patchOption: vi.fn(() => Promise.resolve()),
  analyseItem: vi.fn(() => Promise.resolve()),
  keepOption: vi.fn(),
}))
const { patchItem, patchExploration, patchOption, analyseItem, keepOption, ApiError } = await import('../api')
const { useItemActions } = await import('./actions')
const { undoHistory } = await import('./history')

afterEach(() => {
  cleanup()
  undoHistory.clear()
  vi.clearAllMocks()
})

function setup() {
  const qc = new QueryClient()
  qc.setQueryData(keys.items('b1'), [makeItem({ id: 'a', board_id: 'b1', x: 0, y: 0 })])
  const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  return { qc, ...renderHook(() => useItemActions('b1'), { wrapper }) }
}

describe('useItemActions undo (⌘Z)', () => {
  it('undoes item moves and option reverts from the shared board history, newest first', () => {
    const { result, qc } = setup()
    const moves = [{ id: 'a', from: { x: 0, y: 0 }, to: { x: 50, y: 60 } }]
    act(() => result.current.commitRelease({ moves, hubs: [], dock: [], settled: new Map() }, { locked: false }))
    const revert = vi.fn()
    undoHistory.pushRevert(revert) // e.g. an option dismissed in the drawer
    let undone = false
    act(() => {
      undone = result.current.undo()
    })
    expect(undone).toBe(true)
    expect(revert).toHaveBeenCalledOnce()
    act(() => {
      undone = result.current.undo()
    })
    expect(undone).toBe(true)
    expect(qc.getQueryData<{ x: number }[]>(keys.items('b1'))?.[0].x).toBe(0)
    expect(patchItem).toHaveBeenLastCalledWith('a', { x: 0, y: 0 })
    expect(result.current.undo()).toBe(false)
  })
})

describe('useItemActions reanalyse', () => {
  it('posts the analyse request and shows the item as pending', async () => {
    const { result, qc } = setup()
    qc.setQueryData(keys.items('b1'), [makeItem({ id: 'a', board_id: 'b1', parse_status: 'failed', parse_error_code: 'DAILY_LIMIT' })])
    await act(() => result.current.reanalyse('a'))
    expect(analyseItem).toHaveBeenCalledWith('a')
    const [item] = qc.getQueryData<{ parse_status: string; parse_error_code: string | null }[]>(keys.items('b1'))!
    expect([item.parse_status, item.parse_error_code]).toEqual(['pending', null])
  })

  it('a refusal is thrown to the caller and the item is left as it was', async () => {
    vi.mocked(analyseItem).mockRejectedValueOnce(new ApiError(429, 'DAILY_LIMIT', 'Daily limit reached'))
    const { result, qc } = setup()
    await expect(result.current.reanalyse('a')).rejects.toMatchObject({ code: 'DAILY_LIMIT' })
    expect(qc.getQueryData<{ parse_status: string }[]>(keys.items('b1'))![0].parse_status).toBe('completed')
  })
})

describe('useItemActions keepOption', () => {
  it('a refusal shows the server message in the action error line', async () => {
    vi.mocked(keepOption).mockRejectedValueOnce(new ApiError(429, 'DAILY_LIMIT', 'Daily limit reached'))
    const { result } = setup()
    await act(() => result.current.keepOption('a'))
    expect(result.current.error).toBe('Could not keep this option: Daily limit reached')
  })
})

describe('useItemActions commitRelease', () => {
  function board() {
    const s = setup()
    s.qc.setQueryData(keys.items('b1'), [
      makeItem({ id: 'a', board_id: 'b1', x: 0, y: 0 }),
      makeItem({ id: 't1', board_id: 'b1', x: 600, y: 0, w: 168, h: 105 }),
    ])
    s.qc.setQueryData(keys.explorations('b1'), [
      exp('e1', 'hand_style', [opt('o2', { kept_item_id: 't1', status: 'kept' })], 'a', { dx: null, dy: null }),
    ])
    const items = () => s.qc.getQueryData<{ id: string; x: number; y: number; w: number; h: number }[]>(keys.items('b1'))!
    const e1 = () => s.qc.getQueryData<{ dx: number | null; dy: number | null; options: { undocked: boolean }[] }[]>(keys.explorations('b1'))![0]
    return { ...s, items, e1 }
  }
  const plan: ReleasePlan = {
    moves: [
      { id: 'a', from: { x: 0, y: 0 }, to: { x: 50, y: 50 }, plain: true },
      { id: 't1', from: { x: 600, y: 0 }, to: { x: 900, y: 40 } },
    ],
    hubs: [{ explorationId: 'e1', from: null, to: { dx: 320, dy: 10 } }],
    dock: [{ optionId: 'o2', itemId: 't1', undocked: true, size: { w: 300, h: 187.5 }, from: { w: 168, h: 105 } }],
    settled: new Map(),
  }

  it('commitRelease is one undo step', () => {
    const { result, items, e1 } = board()
    act(() => result.current.commitRelease(plan, { locked: false }))
    expect(items().map((i) => [i.x, i.y, i.w, i.h])).toEqual([[50, 50, 200, 150], [900, 40, 300, 187.5]])
    expect([e1().dx, e1().dy, e1().options[0].undocked]).toEqual([320, 10, true])
    expect(patchItem).toHaveBeenCalledWith('a', { x: 50, y: 50 })
    expect(patchItem).toHaveBeenCalledWith('t1', { x: 900, y: 40, w: 300, h: 187.5 })
    expect(patchExploration).toHaveBeenCalledWith('e1', { dx: 320, dy: 10 })
    expect(patchOption).toHaveBeenCalledWith('o2', { undocked: true })
    expect(undoHistory.size).toBe(1)

    act(() => void result.current.undo())
    expect(items().map((i) => [i.x, i.y, i.w, i.h])).toEqual([[0, 0, 200, 150], [600, 0, 168, 105]])
    expect([e1().dx, e1().dy, e1().options[0].undocked]).toEqual([null, null, false])
    expect(patchItem).toHaveBeenLastCalledWith('t1', { x: 600, y: 0, w: 168, h: 105 })
    expect(patchExploration).toHaveBeenLastCalledWith('e1', { dx: null, dy: null })
    expect(patchOption).toHaveBeenLastCalledWith('o2', { undocked: false })
    expect(undoHistory.size).toBe(0)
  })

  it('locked commitRelease writes nothing', () => {
    const { result, items, e1 } = board()
    const local = { ...plan, moves: [] }
    act(() => result.current.commitRelease(local, { locked: true }))
    expect(items()[1]).toMatchObject({ w: 300, h: 187.5 })
    expect([e1().dx, e1().dy, e1().options[0].undocked]).toEqual([320, 10, true])
    act(() => void result.current.undo())
    expect([e1().dx, e1().dy, e1().options[0].undocked]).toEqual([null, null, false])
    expect(items()[1]).toMatchObject({ w: 168, h: 105 })
    expect(patchItem).not.toHaveBeenCalled()
    expect(patchExploration).not.toHaveBeenCalled()
    expect(patchOption).not.toHaveBeenCalled()
  })

  it('locked commitRelease saves only a grabbed plain item (open in the demo); the undocked take stays local', () => {
    const { result, items } = board()
    act(() => result.current.commitRelease(plan, { locked: true }))
    expect(items()[1]).toMatchObject({ x: 900, y: 40, w: 300 })
    expect(vi.mocked(patchItem).mock.calls).toEqual([['a', { x: 50, y: 50 }]])
    act(() => void result.current.undo())
    expect(vi.mocked(patchItem).mock.calls).toEqual([['a', { x: 50, y: 50 }], ['a', { x: 0, y: 0 }]])
    expect(patchExploration).not.toHaveBeenCalled()
    expect(patchOption).not.toHaveBeenCalled()
  })

  it('a failed write puts the whole release back, writes it back, drops its undo step and reports once', async () => {
    vi.mocked(patchOption).mockRejectedValueOnce(new Error('boom'))
    vi.mocked(patchExploration).mockRejectedValueOnce(new Error('again'))
    const { result, qc, items, e1 } = board()
    const invalidate = vi.spyOn(qc, 'invalidateQueries')
    await act(async () => result.current.commitRelease(plan, { locked: false }))
    expect(items().map((i) => [i.x, i.y, i.w, i.h])).toEqual([[0, 0, 200, 150], [600, 0, 168, 105]])
    expect([e1().dx, e1().dy, e1().options[0].undocked]).toEqual([null, null, false])
    expect(patchItem).toHaveBeenLastCalledWith('t1', { x: 600, y: 0, w: 168, h: 105 })
    expect(patchOption).toHaveBeenLastCalledWith('o2', { undocked: false })
    expect(undoHistory.size).toBe(0)
    // one report (the first failure), one resync
    expect(result.current.error).toBe('Could not save position: again')
    expect(invalidate.mock.calls.filter(([q]) => q?.queryKey?.[0] === 'explorations')).toHaveLength(1)
  })
})
