import { QueryClient } from '@tanstack/react-query'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { keys } from '../api'
import { makeItem } from '../test/fixtures'

vi.mock('../api', async (orig) => ({ ...(await orig<typeof import('../api')>()), keepOption: vi.fn() }))
const api = await import('../api')
const { keepOptionItem } = await import('./options')

afterEach(() => vi.clearAllMocks())

const cached = (qc: QueryClient) => (qc.getQueryData(keys.items('b1')) as ReturnType<typeof makeItem>[])[0]

describe('keepOptionItem', () => {
  it('Keep calls keepOption and removes the outline at once', async () => {
    const qc = new QueryClient()
    qc.setQueryData(keys.items('b1'), [makeItem({ id: 'o', option_run_id: 'r1' })])
    vi.mocked(api.keepOption).mockResolvedValue(makeItem({ id: 'o', option_run_id: null }))
    const p = keepOptionItem(qc, 'b1', 'o')
    expect(cached(qc).option_run_id).toBeNull()
    await p
    expect(api.keepOption).toHaveBeenCalledWith('o')
    expect(cached(qc).option_run_id).toBeNull()
  })
  it('puts the outline back when the server refuses', async () => {
    const qc = new QueryClient()
    qc.setQueryData(keys.items('b1'), [makeItem({ id: 'o', option_run_id: 'r1' })])
    vi.mocked(api.keepOption).mockRejectedValue(new Error('no'))
    await expect(keepOptionItem(qc, 'b1', 'o')).rejects.toThrow()
    expect(cached(qc).option_run_id).toBe('r1')
  })
})
