import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../api'

vi.mock('../api', async (orig) => ({
  ...(await orig<typeof import('../api')>()),
  putInto: vi.fn(),
}))
const { putInto } = await import('../api')
const { GhostTile } = await import('./GhostTile')
const { addGhost, ghostStore, removeGhost } = await import('./ghosts')
const { createLivingWorld } = await import('../living/world')
const { LivingProvider } = await import('../living/useLiving')
type Ghost = import('./ghosts').Ghost

const request: Ghost['request'] = { targetId: 't', body: { source_id: 's', spots: [{ part: 'front_wheel' }], words: 'soft' } }
const ghost = (over: Partial<Ghost> = {}): Ghost => ({
  jobId: 'j1', boardId: 'b', targetId: 't', x: 100, y: 50, w: 200, h: 120, request, error: null, ...over,
})
const all = () => ghostStore.get().ghosts

afterEach(() => {
  cleanup()
  all().forEach((g) => removeGhost(g.jobId))
  vi.clearAllMocks()
})

function show(g: Ghost) {
  addGhost(g)
  const world = createLivingWorld({ reduced: true })
  render(
    <LivingProvider world={world}>
      <GhostTile ghost={g} view={{ x: 10, y: 0, scale: 2 }} />
    </LivingProvider>,
  )
}

describe('GhostTile', () => {
  it('a dashed box where the result will land, reading "Putting in…"', () => {
    show(ghost())
    expect(screen.getByText('Putting in…')).toBeTruthy()
    const box = document.querySelector<HTMLElement>('.put-ghost')!
    expect(box.style.left).toBe('210px')
    expect(box.style.top).toBe('100px')
    expect(box.style.width).toBe('400px')
    expect(box.style.height).toBe('240px')
    expect(screen.queryByRole('button', { name: 'Retry' })).toBeNull()
  })

  it('with an error: the message, Retry and Dismiss', () => {
    show(ghost({ error: 'The model could not do it' }))
    expect(screen.getByText('The model could not do it')).toBeTruthy()
    expect(screen.queryByText('Putting in…')).toBeNull()
    expect(screen.getByRole('button', { name: 'Retry' })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Dismiss' })).toBeTruthy()
  })

  it('an error with no message falls back to "Could not put it in"', () => {
    show(ghost({ error: '' }))
    expect(screen.getByText('Could not put it in')).toBeTruthy()
  })

  it('Dismiss removes the ghost', () => {
    show(ghost({ error: 'nope' }))
    fireEvent.click(screen.getByRole('button', { name: 'Dismiss' }))
    expect(all()).toHaveLength(0)
  })

  it('Retry asks again with the stored request; on success a ghost with the new job replaces it', async () => {
    vi.mocked(putInto).mockResolvedValue({ job_id: 'j2', x: 120, y: 60, w: 200, h: 120 })
    show(ghost({ error: 'nope' }))
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
    })
    expect(putInto).toHaveBeenCalledTimes(1)
    expect(putInto).toHaveBeenCalledWith('t', request.body)
    expect(all().map((g) => [g.jobId, g.error, g.x, g.y])).toEqual([['j2', null, 120, 60]])
  })

  it('Retry that fails again updates the error', async () => {
    vi.mocked(putInto).mockRejectedValue(new ApiError(429, 'RATE_LIMITED', 'Daily limit reached'))
    show(ghost({ error: 'nope' }))
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
    })
    expect(all().map((g) => [g.jobId, g.error])).toEqual([['j1', 'Daily limit reached']])
  })
})
