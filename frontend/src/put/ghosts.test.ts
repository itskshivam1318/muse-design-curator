import { afterEach, describe, expect, it } from 'vitest'
import { QueryClient } from '@tanstack/react-query'
import { applyEvent } from '../events'
import { addGhost, failGhost, type Ghost, ghostStore, removeGhost } from './ghosts'

const ghost = (over: Partial<Ghost> = {}): Ghost => ({
  jobId: 'j1',
  boardId: 'b',
  targetId: 't',
  x: 1,
  y: 2,
  w: 3,
  h: 4,
  request: { targetId: 't', body: { source_id: 's', spots: [{ part: 'p' }] } },
  error: null,
  ...over,
})
const all = () => ghostStore.get().ghosts

afterEach(() => all().forEach((g) => removeGhost(g.jobId)))

describe('ghosts', () => {
  it('lists a ghost for its board only', () => {
    addGhost(ghost())
    addGhost(ghost({ jobId: 'j2', boardId: 'other' }))
    expect(ghostStore.forBoard('b').map((g) => g.jobId)).toEqual(['j1'])
  })

  it('put.done removes it', () => {
    addGhost(ghost())
    applyEvent(new QueryClient(), 'b', 'put.done', { job_id: 'j1', item_id: 'i' })
    expect(all()).toEqual([])
  })

  it('put.failed keeps it with the message', () => {
    addGhost(ghost())
    applyEvent(new QueryClient(), 'b', 'put.failed', { job_id: 'j1', code: 'X', message: 'nope' })
    expect(all().map((g) => g.error)).toEqual(['nope'])
  })

  it('removing or failing an unknown id is a no-op', () => {
    addGhost(ghost())
    const before = all()
    removeGhost('zzz')
    failGhost('zzz', 'm')
    expect(all()).toBe(before)
  })

  it('a job done before its ghost is added leaves no ghost', () => {
    applyEvent(new QueryClient(), 'b', 'put.done', { job_id: 'early1', item_id: 'i' })
    addGhost(ghost({ jobId: 'early1' }))
    expect(all()).toEqual([])
  })

  it('a job failed before its ghost is added gives a failed ghost', () => {
    applyEvent(new QueryClient(), 'b', 'put.failed', { job_id: 'early2', code: 'X', message: 'too bad' })
    addGhost(ghost({ jobId: 'early2' }))
    expect(all().map((g) => g.error)).toEqual(['too bad'])
  })
})
