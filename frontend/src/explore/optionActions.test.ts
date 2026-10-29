import { QueryClient } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError, type Exploration, type ExploreOption, keys } from '../api'
import { undoHistory } from '../canvas/history'
import { hoverStore, setHoveredOption } from './hover'

vi.mock('../api', async (orig) => ({ ...(await orig<typeof import('../api')>()), patchOption: vi.fn() }))
const { patchOption } = await import('../api')
const { dismissOption, moveOption } = await import('./optionActions')

function opt(over: Partial<ExploreOption> = {}): ExploreOption {
  return {
    id: 'o1', exploration_id: 'e1', parent_option_id: null, batch: 1, steer: null, name: 'Brushed',
    description: '', distance: 'near', value: 'brushed', keeps: [], status: 'open', last_error: null, kept_item_id: null, takes: [],
    x: null, y: null, ...over,
  }
}

function setup(option = opt()) {
  const qc = new QueryClient()
  const list: Exploration[] = [{ id: 'e1', board_id: 'b1', item_id: 'i1', key: 'case_finish', options: [option] }]
  qc.setQueryData(keys.explorations('b1'), list)
  const current = () => qc.getQueryData<Exploration[]>(keys.explorations('b1'))![0].options[0]
  return { qc, current }
}

/** Run the newest undo entry (what ⌘Z does) and let its request settle. */
async function undo() {
  const entry = undoHistory.pop()
  expect(entry?.kind).toBe('revert')
  if (entry?.kind === 'revert') entry.revert()
  await vi.waitFor(() => expect(patchOption).toHaveBeenCalledTimes(2))
}

beforeEach(() => {
  vi.mocked(patchOption).mockReset()
  undoHistory.clear()
})
afterEach(() => setHoveredOption(null))

describe('option actions', () => {
  it('moving a note saves it at once, and undo puts it back', async () => {
    vi.mocked(patchOption).mockImplementation((id, body) => Promise.resolve(opt({ id, x: body.x, y: body.y })))
    const { qc, current } = setup()
    const saving = moveOption(qc, 'b1', 'o1', { x: 260, y: -10 }, { x: 400, y: 80 })
    expect(current()).toMatchObject({ x: 400, y: 80 }) // optimistic
    await saving
    expect(patchOption).toHaveBeenCalledWith('o1', { x: 400, y: 80 })
    expect(undoHistory.size).toBe(1)
    await undo()
    expect(patchOption).toHaveBeenLastCalledWith('o1', { x: 260, y: -10 })
    await vi.waitFor(() => expect(current()).toMatchObject({ x: 260, y: -10 }))
    expect(undoHistory.size).toBe(0) // an undo is not itself recorded
  })

  it('a failed move puts the note back where it was and records nothing', async () => {
    vi.mocked(patchOption).mockRejectedValue(new ApiError(403, 'DEMO_LOCKED', 'Unlock the demo'))
    const { qc, current } = setup()
    await expect(moveOption(qc, 'b1', 'o1', { x: 260, y: -10 }, { x: 400, y: 80 })).rejects.toThrow('Unlock the demo')
    expect(current()).toMatchObject({ x: null, y: null })
    expect(undoHistory.size).toBe(0)
  })

  it('a dismiss is undone by reopening the option', async () => {
    vi.mocked(patchOption)
      .mockResolvedValueOnce(opt({ status: 'dismissed' }))
      .mockResolvedValueOnce(opt({ status: 'visualized' })) // the server restores visualized when it has items
    const { qc, current } = setup(opt({ status: 'visualized' }))
    setHoveredOption('o1')
    await dismissOption(qc, 'b1', opt({ status: 'visualized' }))
    expect(patchOption).toHaveBeenCalledWith('o1', { status: 'dismissed' })
    expect(current().status).toBe('dismissed')
    expect(hoverStore.get()).toBeNull()
    await undo()
    expect(patchOption).toHaveBeenLastCalledWith('o1', { status: 'open' })
    await vi.waitFor(() => expect(current().status).toBe('visualized'))
  })

  it('a failed dismiss records nothing', async () => {
    vi.mocked(patchOption).mockRejectedValue(new Error('offline'))
    const { qc, current } = setup()
    await expect(dismissOption(qc, 'b1', opt())).rejects.toThrow('offline')
    expect(current().status).toBe('open')
    expect(undoHistory.size).toBe(0)
  })
})
