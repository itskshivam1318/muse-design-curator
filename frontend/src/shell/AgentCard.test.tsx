import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { type AgentMessage, type AgentRun, type AgentStep, keys } from '../api'
import { selection } from '../canvas/selection'
import { applyEvent, boardActivity } from '../events'
import { setBoard, track } from '../telemetry'
import { makeMessage, makeRun, makeStep } from '../test/fixtures'
import { AgentCard } from './AgentCard'
import { closeSpotlight, spotlightStore } from './spotlight'
import { partConfirmStore } from './partConfirm'

beforeEach(() => {
  vi.spyOn(globalThis, 'fetch').mockImplementation(async () => new Response('{}', { status: 500 }))
})

afterEach(() => {
  cleanup()
  boardActivity.clear()
  selection.reset()
  closeSpotlight()
  window.history.replaceState(null, '', '/')
  vi.restoreAllMocks()
})

function renderCard(
  opts: {
    run?: AgentRun
    steps?: AgentStep[]
    /** newest first; each run's steps are in `stepsByRun` */
    runs?: AgentRun[]
    stepsByRun?: Record<string, AgentStep[]>
    locked?: boolean
    /** the server's chat model; off unless given */
    chat?: boolean
    messagesByRun?: Record<string, AgentMessage[]>
    onFocusItem?: (id: string) => void
  } = {},
) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })
  qc.setQueryData(keys.demo, { demo_mode: opts.locked === true, unlocked: false })
  qc.setQueryData(keys.chatStatus(), { available: opts.chat === true, reason: opts.chat ? null : 'no model' })
  for (const [runId, messages] of Object.entries(opts.messagesByRun ?? {})) qc.setQueryData(keys.agentMessages(runId), messages)
  const runs = opts.runs ?? (opts.run ? [opts.run] : [])
  qc.setQueryData(keys.agentRuns('b1'), runs)
  for (const r of runs) {
    const steps = opts.stepsByRun?.[r.id] ?? (r === opts.run ? opts.steps : undefined) ?? []
    qc.setQueryData(keys.agentRun(r.id), { ...r, steps })
  }
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
    expect(input.placeholder).toBe(NO_MODEL)
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

  it('stop run pauses an open run', async () => {
    const fetchSpy = vi
      .spyOn(globalThis, 'fetch')
      .mockImplementation(async () => new Response(JSON.stringify(makeRun({ status: 'paused' })), { status: 200 }))
    const qc = renderCard({ run: makeRun({ status: 'needs_input' }), steps })
    fireEvent.click(screen.getByRole('button', { name: 'Stop run' }))
    await waitFor(() => expect(qc.getQueryData<AgentRun[]>(keys.agentRuns('b1'))![0].status).toBe('paused'))
    const [url, init] = fetchSpy.mock.calls.at(-1)!
    expect(String(url)).toContain('/api/agent-runs/r1')
    expect(init?.method).toBe('PATCH')
    expect(JSON.parse(String(init?.body))).toEqual({ status: 'paused' })
    expect(screen.queryByRole('button', { name: 'Stop run' })).toBeNull()
  })

  it('stop run is offered only on an open run, and not when locked', () => {
    renderCard({ run: makeRun({ status: 'running' }), steps, locked: true })
    expect(screen.queryByRole('button', { name: 'Stop run' })).toBeNull()
    cleanup()
    renderCard({ run: makeRun({ status: 'done' }), steps })
    expect(screen.queryByRole('button', { name: 'Stop run' })).toBeNull()
    cleanup()
    renderCard({ run: makeRun({ status: 'running' }), steps })
    expect(screen.getByRole('button', { name: 'Stop run' })).toBeTruthy()
  })

  it('says so when the run cannot be stopped', async () => {
    renderCard({ run: makeRun({ status: 'running' }), steps })
    fireEvent.click(screen.getByRole('button', { name: 'Stop run' }))
    expect((await screen.findByRole('alert')).textContent).toBe('Could not stop the run.')
  })

  it('placeholder says Claude Code is working', () => {
    renderCard({ run: makeRun({ source: 'mcp', status: 'running' }), steps })
    const input = screen.getByLabelText('Message Muse') as HTMLInputElement
    expect(input.disabled).toBe(true)
    expect(input.placeholder).toBe('Claude Code is working')
  })

  it('placeholder is unchanged once the run is done', () => {
    renderCard({ run: makeRun({ source: 'mcp', status: 'done' }), steps })
    expect((screen.getByLabelText('Message Muse') as HTMLInputElement).placeholder).toBe(NO_MODEL)
  })
})

const NO_MODEL = 'Chat needs Muse Spark (REASONING_PROVIDER=muse-spark)'

describe('AgentCard, chat', () => {
  const input = () => screen.getByLabelText('Message Muse') as HTMLInputElement

  it('is open when the server has a chat model', () => {
    renderCard({ chat: true })
    expect(input().disabled).toBe(false)
    expect(input().placeholder).toBe('Ask Muse about this board')
  })

  it('is off in the demo, before anything else', () => {
    renderCard({ chat: true, locked: true, run: makeRun({ source: 'mcp', status: 'running' }) })
    expect(input().disabled).toBe(true)
    expect(input().placeholder).toBe('Chat is off in the demo. Use “Show me how” to watch a run.')
  })

  it('waits while a Claude Code run is open, even one not shown', () => {
    const mcp = makeRun({ id: 'r1', source: 'mcp', status: 'needs_input', created_at: '2026-11-03T09:00:00Z' })
    const muse = makeRun({ id: 'r2', source: 'muse', status: 'waiting', created_at: '2026-11-03T10:00:00Z' })
    renderCard({ chat: true, runs: [muse, mcp] })
    expect(input().disabled).toBe(true)
    expect(input().placeholder).toBe('Claude Code is working')
  })

  it('shows the chat chip for the selection', () => {
    act(() => selection.select(['itm_1', 'itm_2']))
    renderCard({ chat: true })
    expect(screen.getByText('About: 2 pictures selected')).toBeTruthy()
  })

  it('AgentCard shows New chat for a waiting muse run', async () => {
    const run = makeRun({ source: 'muse', status: 'waiting' })
    vi.mocked(fetch).mockImplementation(async (url) =>
      String(url).endsWith('/agent-runs/r1/new-chat')
        ? new Response(JSON.stringify({ ...run, status: 'done' }), { status: 200, headers: { 'Content-Type': 'application/json' } })
        : new Response('{}', { status: 500 }),
    )
    const qc = renderCard({ chat: true, run, messagesByRun: { r1: [] } })
    fireEvent.click(screen.getByRole('button', { name: 'New chat' }))
    await waitFor(() => expect(qc.getQueryData<AgentRun[]>(keys.agentRuns('b1'))?.[0].status).toBe('done'))
    expect(screen.queryByRole('button', { name: 'New chat' })).toBeNull()
  })

  it('no New chat while the muse run is working, for a Claude Code run, or when locked', () => {
    renderCard({ chat: true, run: makeRun({ source: 'muse', status: 'running' }), messagesByRun: { r1: [] } })
    expect(screen.queryByRole('button', { name: 'New chat' })).toBeNull()
    expect(screen.getByRole('button', { name: 'Stop run' })).toBeTruthy()
    cleanup()
    renderCard({ chat: true, run: makeRun({ source: 'mcp', status: 'needs_input' }) })
    expect(screen.queryByRole('button', { name: 'New chat' })).toBeNull()
    cleanup()
    renderCard({ locked: true, run: makeRun({ source: 'muse', status: 'waiting' }), messagesByRun: { r1: [] } })
    expect(screen.queryByRole('button', { name: 'New chat' })).toBeNull()
  })

  it('a muse run shows the thread, not the step list', () => {
    const run = makeRun({ source: 'muse', status: 'waiting', goal: 'Warmer palette' })
    renderCard({
      chat: true,
      run,
      steps: [makeStep({ say: 'Reading the board', created_at: '2026-11-04T10:00:01Z' })],
      messagesByRun: {
        r1: [
          makeMessage({ id: 'm1', role: 'person', text: 'Warmer palette', created_at: '2026-11-04T10:00:00Z' }),
          makeMessage({ id: 'm2', role: 'agent', text: 'Try itm_1', created_at: '2026-11-04T10:00:02Z' }),
        ],
      },
    })
    expect(screen.getByText('Try itm_1')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Show activity' }))
    const thread = screen.getByRole('list', { name: 'Chat' })
    expect(within(thread).getAllByRole('listitem').map((li) => li.textContent)).toEqual([
      expect.stringContaining('Warmer palette'),
      expect.stringContaining('Reading the board'),
      expect.stringContaining('Try itm_1'),
    ])
    expect(screen.queryByRole('list', { name: 'Steps' })).toBeNull()
    expect(screen.getByRole('link', { name: 'Download trace' }).getAttribute('href')).toBe('/api/agent-runs/r1/trace')
  })

  it('a sent message shows its run', async () => {
    const run = makeRun({ id: 'r9', source: 'muse', status: 'running', goal: 'Warmer' })
    const message = makeMessage({ id: 'm9', run_id: 'r9', role: 'person', text: 'Warmer' })
    const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
    vi.mocked(fetch).mockImplementation(async (url) => {
      if (String(url).endsWith('/boards/b1/agent/messages')) return json({ run, message })
      // a run the card has no messages for is fetched afresh
      if (String(url).endsWith('/agent-runs/r9/messages')) return json({ messages: [message] })
      return new Response('{}', { status: 500 })
    })
    const old = makeRun({ id: 'r1', source: 'mcp', status: 'done', goal: 'Old goal' })
    const qc = renderCard({ chat: true, run: old })
    qc.setQueryData(keys.agentRun('r9'), { ...run, steps: [] })
    fireEvent.change(input(), { target: { value: 'Warmer' } })
    fireEvent.keyDown(input(), { key: 'Enter' })
    expect(await screen.findByRole('list', { name: 'Chat' })).toBeTruthy()
    expect(within(screen.getByRole('list', { name: 'Chat' })).getByText('Warmer')).toBeTruthy()
  })
})

describe('AgentCard, questions', () => {
  it('a choice answers the question with a short line', async () => {
    const run = makeRun({ source: 'muse', status: 'needs_input', goal: 'Warmer' })
    const question = makeMessage({
      id: 'q1',
      role: 'question',
      text: 'Which palette?',
      data: { call_id: 'c1', tool: 'ask_user', args: { question: 'Which palette?', choices: ['Warm', 'Cool'] } },
    })
    const reply = makeMessage({ id: 'm9', role: 'person', text: 'Warm', created_at: '2026-11-04T10:00:05Z' })
    const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
    vi.mocked(fetch).mockImplementation(async (url) =>
      String(url).endsWith('/boards/b1/agent/messages') ? json({ run: { ...run, status: 'running' }, message: reply }) : new Response('{}', { status: 500 }),
    )
    renderCard({ chat: true, run, messagesByRun: { r1: [question] } })
    fireEvent.click(screen.getByRole('button', { name: 'Show activity' }))
    fireEvent.click(screen.getByRole('button', { name: 'Warm' }))
    await waitFor(() => expect(vi.mocked(fetch).mock.calls.some(([u]) => String(u).endsWith('/boards/b1/agent/messages'))).toBe(true))
    const [, init] = vi.mocked(fetch).mock.calls.find(([u]) => String(u).endsWith('/boards/b1/agent/messages'))!
    expect(JSON.parse(String(init?.body))).toEqual({ text: 'Warm', selection: [], answer: { call_id: 'c1', choice: 'Warm' } })
  })

  it('an answered question shows no buttons, and takes no second answer', async () => {
    const run = makeRun({ source: 'muse', status: 'needs_input', goal: 'Warmer' })
    const question = makeMessage({
      id: 'q1',
      role: 'question',
      text: 'Is this the shade?',
      data: { call_id: 'c2', tool: 'confirm_part', args: { item_id: 'itm_7', part: 'shade', why: 'recolour' }, region: null },
    })
    const reply = makeMessage({ id: 'm9', role: 'person', text: 'Yes', created_at: '2026-11-04T10:00:05Z' })
    const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
    vi.mocked(fetch).mockImplementation(async (url) =>
      String(url).endsWith('/boards/b1/agent/messages') ? json({ run: { ...run, status: 'running' }, message: reply }) : new Response('{}', { status: 500 }),
    )
    const qc = renderCard({ chat: true, run, messagesByRun: { r1: [question] } })
    fireEvent.click(screen.getByRole('button', { name: 'Show activity' }))
    const yes = screen.getByRole('button', { name: 'Yes' })
    fireEvent.click(yes)
    await waitFor(() => expect(vi.mocked(fetch).mock.calls.some(([u]) => String(u).endsWith('/boards/b1/agent/messages'))).toBe(true))
    // the server closes the question and says so
    act(() => applyEvent(qc, 'b1', 'agent.question', { ...question, answered: true }))
    await waitFor(() => expect(screen.queryByRole('button', { name: 'Fix' })).toBeNull())
    expect(screen.queryByRole('textbox', { name: 'Answer' })).toBeNull()
    expect(partConfirmStore.get()).toBeNull()
    fireEvent.click(yes) // a stale button
    const posts = vi.mocked(fetch).mock.calls.filter(([u]) => String(u).endsWith('/boards/b1/agent/messages'))
    expect(posts).toHaveLength(1)
  })

  it('says so when the answer cannot be sent', async () => {
    const run = makeRun({ source: 'muse', status: 'needs_input', goal: 'Warmer' })
    const question = makeMessage({
      id: 'q1',
      role: 'question',
      text: 'Is this the shade?',
      data: { call_id: 'c2', tool: 'confirm_part', args: { item_id: 'itm_7', part: 'shade', why: 'recolour' }, region: null },
    })
    renderCard({ chat: true, run, messagesByRun: { r1: [question] } })
    fireEvent.click(screen.getByRole('button', { name: 'Show activity' }))
    fireEvent.click(screen.getByRole('button', { name: 'Yes' }))
    expect(await screen.findByText('Could not send your answer.')).toBeTruthy()
  })
})

describe('AgentCard, replay', () => {
  it('shows Show me how on a finished run with starred steps', () => {
    renderCard({ run: makeRun({ status: 'done' }), steps: [makeStep({ highlight: true })] })
    fireEvent.click(screen.getByRole('button', { name: 'Show me how' }))
    expect(spotlightStore.get()?.runId).toBe('r1')
    expect(spotlightStore.get()?.boardId).toBe('b1')
  })

  it('no button while the run is open or has nothing to play', () => {
    renderCard({ run: makeRun({ status: 'running' }), steps: [makeStep({ highlight: true })] })
    expect(screen.queryByRole('button', { name: 'Show me how' })).toBeNull()
    cleanup()
    renderCard({ run: makeRun({ status: 'done' }), steps: [makeStep({ highlight: true, ok: false })] })
    expect(screen.queryByRole('button', { name: 'Show me how' })).toBeNull()
  })

  it('a locked visitor can still replay', () => {
    renderCard({ locked: true, run: makeRun({ status: 'done' }), steps: [makeStep({ highlight: true })] })
    expect(screen.getByRole('button', { name: 'Show me how' })).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Show activity' }))
    expect(screen.queryByRole('button', { name: 'Highlight step' })).toBeNull()
  })

  const two = () => {
    const r2 = makeRun({ id: 'r2', status: 'running', goal: 'Newer goal', created_at: '2026-11-03T15:40:00Z' })
    const r1 = makeRun({ id: 'r1', status: 'done', goal: 'Older goal', created_at: '2026-11-03T09:05:00Z' })
    return { runs: [r2, r1], stepsByRun: { r1: [makeStep({ id: 's1', run_id: 'r1', highlight: true })], r2: [] } }
  }

  it('lists past runs and replays the one picked', () => {
    renderCard(two())
    fireEvent.click(screen.getByRole('button', { name: 'Show activity' }))
    const select = screen.getByLabelText('Run') as HTMLSelectElement
    // the run's time tells two runs with the same goal apart
    const at = (iso: string) => new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    expect([...select.options].map((o) => [o.value, o.textContent])).toEqual([
      ['r2', `Claude Code · ${at('2026-11-03T15:40:00Z')} · Newer goal`],
      ['r1', `Claude Code · ${at('2026-11-03T09:05:00Z')} · Older goal`],
    ])
    expect(screen.getByText('Newer goal')).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Show me how' })).toBeNull()
    fireEvent.change(select, { target: { value: 'r1' } })
    expect(screen.getByText('Older goal', { selector: 'p' })).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Show me how' }))
    expect(spotlightStore.get()?.runId).toBe('r1')
  })

  it('no picker for a single run', () => {
    renderCard({ run: makeRun() })
    fireEvent.click(screen.getByRole('button', { name: 'Show activity' }))
    expect(screen.queryByLabelText('Run')).toBeNull()
  })

  it('a newer run does not change the run the person picked', () => {
    const { runs, stepsByRun } = two()
    const qc = renderCard({ runs, stepsByRun })
    fireEvent.click(screen.getByRole('button', { name: 'Show activity' }))
    fireEvent.change(screen.getByLabelText('Run'), { target: { value: 'r1' } })
    const r3 = makeRun({ id: 'r3', status: 'running', goal: 'Newest goal' })
    act(() => {
      qc.setQueryData(keys.agentRun('r3'), { ...r3, steps: [] })
      qc.setQueryData(keys.agentRuns('b1'), [r3, ...runs])
    })
    expect((screen.getByLabelText('Run') as HTMLSelectElement).value).toBe('r1')
    expect(screen.getByText('Older goal', { selector: 'p' })).toBeTruthy()
    expect(screen.queryByText('Newest goal', { selector: 'p' })).toBeNull()
  })

  it('collapses while replaying and the button says so', () => {
    renderCard({ run: makeRun({ status: 'done' }), steps: [makeStep({ highlight: true })] })
    fireEvent.click(screen.getByRole('button', { name: 'Show activity' }))
    fireEvent.click(screen.getByRole('button', { name: 'Show me how' }))
    expect(screen.queryByRole('list', { name: 'Steps' })).toBeNull()
    const btn = screen.getByRole('button', { name: 'Replaying…' }) as HTMLButtonElement
    expect(btn.disabled).toBe(true)
    expect(screen.queryByRole('button', { name: 'Show me how' })).toBeNull()
    act(() => closeSpotlight())
    expect(screen.getByRole('button', { name: 'Show me how' })).toBeTruthy()
  })

  it('opens the replay named in the link, once', () => {
    window.history.replaceState(null, '', '/boards/b1?replay=r1')
    renderCard({ run: makeRun({ status: 'done' }), steps: [makeStep({ highlight: true })] })
    expect(spotlightStore.get()?.runId).toBe('r1')
    expect(spotlightStore.get()?.boardId).toBe('b1')
    expect(window.location.search).toBe('')
    expect(window.location.pathname).toBe('/boards/b1')
  })

  it('ignores a link to a run that is not on the board', () => {
    window.history.replaceState(null, '', '/boards/b1?replay=nope')
    renderCard({ run: makeRun({ status: 'done' }), steps: [makeStep({ highlight: true })] })
    expect(spotlightStore.get()).toBeNull()
    expect(window.location.search).toBe('')
  })
})
