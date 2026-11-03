import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { type AgentRun, type AgentStep, keys } from '../api'
import { selection } from '../canvas/selection'
import { applyEvent, boardActivity } from '../events'
import { setBoard, track } from '../telemetry'
import { makeRun, makeStep } from '../test/fixtures'
import { AgentCard } from './AgentCard'

beforeEach(() => {
  vi.spyOn(globalThis, 'fetch').mockImplementation(async () => new Response('{}', { status: 500 }))
})

afterEach(() => {
  cleanup()
  boardActivity.clear()
  selection.reset()
  vi.restoreAllMocks()
})

function renderCard(
  opts: { run?: AgentRun; steps?: AgentStep[]; locked?: boolean; onFocusItem?: (id: string) => void } = {},
) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })
  qc.setQueryData(keys.demo, { demo_mode: opts.locked === true, unlocked: false })
  qc.setQueryData(keys.agentRuns('b1'), opts.run ? [opts.run] : [])
  if (opts.run) qc.setQueryData(keys.agentRun(opts.run.id), { ...opts.run, steps: opts.steps ?? [] })
  render(
    <QueryClientProvider client={qc}>
      <AgentCard boardId="b1" onFocusItem={opts.onFocusItem ?? (() => undefined)} />
    </QueryClientProvider>,
  )
  return qc
}

describe('AgentCard', () => {
  it('says nothing yet on a quiet board', () => {
    renderCard()
    expect(screen.getByText('Muse')).toBeTruthy()
    expect(screen.getByText('Nothing yet.')).toBeTruthy()
  })

  it('shows the latest activity as one sentence', () => {
    boardActivity.push('Added 2 images.')
    boardActivity.push('Palette finished on 3 images.')
    renderCard()
    expect(screen.getByText('Palette finished on 3 images.')).toBeTruthy()
    expect(screen.queryByText('Added 2 images.')).toBeNull()
    act(() => boardActivity.push('Kept Honey.'))
    expect(screen.getByText('Kept Honey.')).toBeTruthy()
  })

  it('has a visible but disabled input with a hidden label', () => {
    renderCard()
    const input = screen.getByLabelText('Message Muse') as HTMLInputElement
    expect(input.disabled).toBe(true)
    expect(input.placeholder).toBe('Agent coming soon')
    expect(screen.getByText('Message Muse').className).toContain('sr-only')
  })

  it('expand lists every entry, newest first', () => {
    boardActivity.push('first')
    boardActivity.push('second')
    boardActivity.push('third')
    renderCard()
    const expand = screen.getByRole('button', { name: 'Show activity' })
    expect(expand.getAttribute('aria-expanded')).toBe('false')
    fireEvent.click(expand)
    expect(expand.getAttribute('aria-expanded')).toBe('true')
    const rows = within(screen.getByRole('list', { name: 'Activity' })).getAllByRole('listitem')
    expect(rows.map((r) => r.textContent)).toEqual([
      expect.stringContaining('third'),
      expect.stringContaining('second'),
      expect.stringContaining('first'),
    ])
    fireEvent.click(expand)
    expect(screen.queryByRole('list', { name: 'Activity' })).toBeNull()
  })

  it('is hidden while the right drawer is open', () => {
    renderCard()
    expect(screen.getByRole('complementary', { name: 'Muse agent' })).toBeTruthy()
    act(() => selection.openDrawer('inspect', 'i1'))
    expect(screen.queryByRole('complementary', { name: 'Muse agent' })).toBeNull()
  })
})

describe('AgentCard, both streams', () => {
  afterEach(() => setBoard(null))

  it('shows the newest of board events and UI actions, and lists both newest first', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-10-29T10:00:00Z'))
    setBoard('b1')
    boardActivity.push('Palette finished on 3 images.')
    vi.setSystemTime(new Date('2026-10-29T10:01:00Z'))
    track('drawer.open', { itemId: 'i1', detail: { kind: 'compare' } })
    vi.useRealTimers()
    renderCard()
    expect(screen.getByText('Opened Compare.')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Show activity' }))
    const rows = within(screen.getByRole('list', { name: 'Activity' })).getAllByRole('listitem')
    expect(rows.map((r) => r.textContent)).toEqual([
      expect.stringContaining('Opened Compare.'),
      expect.stringContaining('Palette finished on 3 images.'),
    ])
  })
})

describe('AgentCard, an agent run', () => {
  const steps = [
    makeStep({ id: 's1', turn: 1, tool: 'read_board', say: 'Reading the board' }),
    makeStep({ id: 's2', turn: 2, tool: 'add_note', args: { text: 'warm' }, say: null, item_ids: ['n1', 'n2'] }),
  ]

  it('shows the latest say collapsed', () => {
    renderCard({ run: makeRun(), steps: [steps[0]] })
    expect(screen.getByText('Claude Code')).toBeTruthy()
    expect(screen.getByText('working')).toBeTruthy()
    expect(screen.getByText('Reading the board')).toBeTruthy()
  })

  it('falls back to the tool name when the latest step says nothing', () => {
    renderCard({ run: makeRun({ source: 'muse', status: 'needs_input' }), steps })
    expect(screen.getByText('Muse')).toBeTruthy()
    expect(screen.getByText('needs you')).toBeTruthy()
    expect(screen.getByText('add_note')).toBeTruthy()
  })

  it('lists goal, deliverables and steps expanded', () => {
    const run = makeRun({
      status: 'done',
      goal: 'Pick a palette',
      deliverables: ['palette', 'type'],
      output: { title: 'Out', sections: [{ deliverable: 'palette', items: [{ item_id: 'i1', why: 'w' }] }], note_ids: [] },
    })
    renderCard({ run, steps })
    fireEvent.click(screen.getByRole('button', { name: 'Show activity' }))
    expect(screen.getByText('Pick a palette')).toBeTruthy()
    const checks = within(screen.getByRole('list', { name: 'Deliverables' })).getAllByRole('checkbox')
    expect(checks.map((c) => [c.closest('label')!.textContent!.trim(), (c as HTMLInputElement).checked])).toEqual([
      ['palette', true],
      ['type', false],
    ])
    const rows = within(screen.getByRole('list', { name: 'Steps' })).getAllByRole('listitem')
    expect(rows.map((r) => r.textContent)).toEqual([
      expect.stringContaining('add_note(text="warm")'),
      expect.stringContaining('Reading the board'),
    ])
    expect(rows[1].textContent).toContain('read_board()')
  })

  it('clicking a step focuses its item', () => {
    const onFocusItem = vi.fn()
    renderCard({ run: makeRun(), steps, onFocusItem })
    fireEvent.click(screen.getByRole('button', { name: 'Show activity' }))
    fireEvent.click(screen.getByRole('button', { name: /add_note\(/ }))
    expect(onFocusItem).toHaveBeenCalledWith('n1')
    // a step with no items is not a button
    expect(screen.queryByRole('button', { name: /read_board\(/ })).toBeNull()
  })

  it('refused step is marked', () => {
    renderCard({ run: makeRun(), steps: [makeStep({ id: 's9', tool: 'finish', ok: false, say: 'Finishing' })] })
    fireEvent.click(screen.getByRole('button', { name: 'Show activity' }))
    const row = within(screen.getByRole('list', { name: 'Steps' })).getByRole('listitem')
    expect(row.textContent).toContain('refused')
    expect(row.className).toContain('refused')
  })

  it('star toggles the step highlight', async () => {
    const fetchSpy = vi
      .spyOn(globalThis, 'fetch')
      .mockImplementation(async () => new Response(JSON.stringify({ ...steps[0], highlight: true }), { status: 200 }))
    const qc = renderCard({ run: makeRun(), steps })
    fireEvent.click(screen.getByRole('button', { name: 'Show activity' }))
    const stars = screen.getAllByRole('button', { name: 'Highlight step' })
    expect(stars).toHaveLength(2)
    fireEvent.click(stars[1])
    await waitFor(() =>
      expect(qc.getQueryData<{ steps: AgentStep[] }>(keys.agentRun('r1'))!.steps[0].highlight).toBe(true),
    )
    const [url, init] = fetchSpy.mock.calls.at(-1)!
    expect(String(url)).toContain('/api/agent-steps/s1')
    expect(init?.method).toBe('PATCH')
    expect(JSON.parse(String(init?.body))).toEqual({ highlight: true })
  })

  it('says so when the highlight cannot be saved', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async () => new Response('{}', { status: 500 }))
    renderCard({ run: makeRun(), steps })
    fireEvent.click(screen.getByRole('button', { name: 'Show activity' }))
    fireEvent.click(screen.getAllByRole('button', { name: 'Highlight step' })[0])
    expect((await screen.findByRole('alert')).textContent).toBe('Could not highlight that step.')
  })

  it('a step that arrives while the run is being fetched is kept', async () => {
    let resolve: (r: Response) => void = () => undefined
    vi.spyOn(globalThis, 'fetch').mockImplementation(() => new Promise<Response>((r) => (resolve = r)))
    const qc = renderCard({ run: makeRun(), steps: [steps[0]] })
    const refetch = qc.refetchQueries({ queryKey: keys.agentRun('r1') })
    act(() => applyEvent(qc, 'b1', 'agent.step', makeStep({ id: 's3', turn: 3, say: 'Adding a note' })))
    // the fetch was answered before s3 was written: it only has s1
    await act(async () => {
      resolve(new Response(JSON.stringify({ ...makeRun(), steps: [steps[0]] }), { status: 200 }))
      await refetch
    })
    expect(await screen.findByText('Adding a note')).toBeTruthy()
    expect(qc.getQueryData<{ steps: AgentStep[] }>(keys.agentRun('r1'))!.steps.map((s) => s.id)).toEqual(['s1', 's3'])
  })

  it('star hidden when locked', () => {
    renderCard({ run: makeRun(), steps, locked: true })
    fireEvent.click(screen.getByRole('button', { name: 'Show activity' }))
    expect(screen.queryByRole('button', { name: 'Highlight step' })).toBeNull()
  })

  it('placeholder says Claude Code is working', () => {
    renderCard({ run: makeRun({ source: 'mcp', status: 'running' }), steps })
    const input = screen.getByLabelText('Message Muse') as HTMLInputElement
    expect(input.disabled).toBe(true)
    expect(input.placeholder).toBe('Claude Code is working')
  })

  it('placeholder is unchanged once the run is done', () => {
    renderCard({ run: makeRun({ source: 'mcp', status: 'done' }), steps })
    expect((screen.getByLabelText('Message Muse') as HTMLInputElement).placeholder).toBe('Agent coming soon')
  })
})
