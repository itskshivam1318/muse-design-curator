import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { SHOWCASE } from '../landing/showcase'
import { BoardsPage } from './BoardsPage'

const CAR = SHOWCASE.boards[0]

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200 })

function serve(boards: { id: string; title: string }[]) {
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
    if (String(input).includes('/demo')) return json({ demo_mode: false, unlocked: false })
    return json({ boards: boards.map((b) => ({ ...b, updated_at: '2026-11-04T00:00:00Z' })) })
  })
}

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <BoardsPage />
    </QueryClientProvider>,
  )
}

describe('BoardsPage', () => {
  it('shows the demo boards as cards above the list, and lists only the rest', async () => {
    serve([
      { id: CAR.boardId, title: 'Car demo' },
      { id: 'brd_mine', title: 'My board' },
    ])
    const { container } = renderPage()
    expect((await screen.findByRole('link', { name: 'Show me how' })).getAttribute('href')).toBe(
      `/boards/${CAR.boardId}?replay=${CAR.runId}`,
    )
    const list = container.querySelector('.board-list') as HTMLElement
    expect(within(list).getByText('My board')).toBeTruthy()
    expect(within(list).queryByText('Car demo')).toBeNull()
    const showcase = container.querySelector('.showcase') as HTMLElement
    expect(showcase.compareDocumentPosition(list) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })

  it('has no demo section when the demo boards are not on this server', async () => {
    serve([{ id: 'brd_mine', title: 'My board' }])
    const { container } = renderPage()
    await screen.findByText('My board')
    expect(container.querySelector('.showcase')).toBeNull()
    expect(screen.queryByText('Your boards')).toBeNull()
  })
})
