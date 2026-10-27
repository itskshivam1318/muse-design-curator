import { QueryClient } from '@tanstack/react-query'
import { describe, expect, it } from 'vitest'
import { type Item, keys } from './api'
import { applyEvent } from './events'
import { makeItem } from './test/fixtures'

function qcWith(items: Item[]) {
  const qc = new QueryClient()
  qc.setQueryData(keys.items('b'), items)
  return qc
}

describe('applyEvent', () => {
  it('board.updated puts the new board (domain) in the cache and refreshes the lens', () => {
    const qc = qcWith([])
    const board = { id: 'b', title: 'T', context: '', domain: null, lens_id: null, created_at: 'x', updated_at: 'x' }
    qc.setQueryData(keys.board('b'), board)
    qc.setQueryData(keys.lens('b'), null)
    applyEvent(qc, 'b', 'board.updated', { board: { ...board, domain: 'watch', lens_id: 'lens_1' } })
    expect(qc.getQueryData<typeof board>(keys.board('b'))).toMatchObject({ domain: 'watch', lens_id: 'lens_1' })
    expect(qc.getQueryState(keys.lens('b'))?.isInvalidated).toBe(true)
  })

  it('item.added upserts once, item.parsed and item.failed patch status, item.removed drops', () => {
    const qc = qcWith([])
    const it1 = makeItem({ id: 'i1', board_id: 'b', parse_status: 'pending' })
    applyEvent(qc, 'b', 'item.added', it1)
    applyEvent(qc, 'b', 'item.added', it1)
    expect(qc.getQueryData<Item[]>(keys.items('b'))).toHaveLength(1)
    applyEvent(qc, 'b', 'item.parsed', { item_id: 'i1', parse_status: 'completed' })
    expect(qc.getQueryData<Item[]>(keys.items('b'))![0].parse_status).toBe('completed')
    applyEvent(qc, 'b', 'item.failed', { item_id: 'i1', error_code: 'MODEL_ERROR' })
    const failed = qc.getQueryData<Item[]>(keys.items('b'))![0]
    expect([failed.parse_status, failed.parse_error_code]).toEqual(['failed', 'MODEL_ERROR'])
    applyEvent(qc, 'b', 'item.updated', { ...it1, x: 99 })
    expect(qc.getQueryData<Item[]>(keys.items('b'))![0].x).toBe(99)
    applyEvent(qc, 'b', 'item.removed', { id: 'i1' })
    expect(qc.getQueryData<Item[]>(keys.items('b'))).toHaveLength(0)
  })

  it('lens.proposed invalidates the board lens', async () => {
    const qc = qcWith([])
    qc.setQueryData(keys.lens('b'), null)
    applyEvent(qc, 'b', 'lens.proposed', { lens_id: 'lens_1', version: 1 })
    expect(qc.getQueryState(keys.lens('b'))?.isInvalidated).toBe(true)
  })
})
