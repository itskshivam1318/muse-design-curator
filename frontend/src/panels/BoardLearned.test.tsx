import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { type BoardContextView, keys } from '../api'
import { BoardLearned } from './BoardLearned'

vi.mock('../api', async (orig) => ({
  ...(await orig<typeof import('../api')>()),
  acceptOffer: vi.fn(),
  declineOffer: vi.fn(),
}))
import { acceptOffer, declineOffer } from '../api'

afterEach(cleanup)

const offer = { label: 'Dial finish', dim_type: 'physical' as const, kind: 'enum' as const, part: 'dial', count: 4, total: 9 }
const view: BoardContextView = { your_words: 'dress watch', learned: ['Prefers brushed steel'], offers: [offer] }

function setup() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })
  qc.setQueryData(keys.boardContext('b1'), view)
  render(
    <QueryClientProvider client={qc}>
      <BoardLearned boardId="b1" />
    </QueryClientProvider>,
  )
}

describe('BoardLearned', () => {
  it('renders learned lines and the offer copy', () => {
    setup()
    expect(screen.getByText('What Muse has learned')).toBeTruthy()
    expect(screen.getByText('Prefers brushed steel')).toBeTruthy()
    expect(screen.getByText('Dial finish · seen on 4 of 9')).toBeTruthy()
  })

  it('Add to board calls acceptOffer and the card disappears', async () => {
    vi.mocked(acceptOffer).mockResolvedValue({ ...view, offers: [] })
    setup()
    fireEvent.click(screen.getByRole('button', { name: 'Add to board' }))
    await waitFor(() => expect(screen.queryByText(/seen on/)).toBeNull())
    expect(acceptOffer).toHaveBeenCalledWith('b1', { label: 'Dial finish', dim_type: 'physical', kind: 'enum', part: 'dial' })
  })

  it('Keep item-only calls declineOffer', async () => {
    vi.mocked(declineOffer).mockResolvedValue({ ...view, offers: [] })
    setup()
    fireEvent.click(screen.getByRole('button', { name: 'Keep item-only' }))
    await waitFor(() => expect(screen.queryByText(/seen on/)).toBeNull())
    expect(declineOffer).toHaveBeenCalledWith('b1', { label: 'Dial finish', dim_type: 'physical', kind: 'enum', part: 'dial' })
  })
})
