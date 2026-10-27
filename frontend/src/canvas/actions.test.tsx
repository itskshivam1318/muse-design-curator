import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, renderHook } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { keys } from '../api'
import { makeItem } from '../test/fixtures'

vi.mock('../api', async (orig) => ({ ...(await orig<typeof import('../api')>()), patchItem: vi.fn(() => Promise.resolve()) }))
const { patchItem } = await import('../api')
const { useItemActions } = await import('./actions')
const { undoHistory } = await import('./history')

afterEach(() => {
  cleanup()
  undoHistory.clear()
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
    act(() => result.current.move([{ id: 'a', from: { x: 0, y: 0 }, to: { x: 50, y: 60 } }]))
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
