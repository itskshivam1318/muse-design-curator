import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import App from '../App'
import { LandingPage } from './LandingPage'
import { SHOWCASE } from './showcase'

const CAR = SHOWCASE.boards[0]
const UI = SHOWCASE.boards[1]

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  SHOWCASE.videoUrl = null
  window.history.pushState(null, '', '/')
})

const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200 })

function serve(boardIds: string[], demo = true) {
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
    const url = String(input)
    if (url.includes('/demo')) return json({ demo_mode: demo, unlocked: false })
    return json({ boards: boardIds.map((id) => ({ id, title: id, updated_at: '2026-11-04T00:00:00Z' })) })
  })
}

function renderWith(ui: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

describe('LandingPage', () => {
  it('links each present board to its replay', async () => {
    serve([CAR.boardId, UI.boardId])
    renderWith(<LandingPage />)
    const links = await screen.findAllByRole('link', { name: 'Show me how' })
    expect(links.map((l) => l.getAttribute('href'))).toEqual([
      `/boards/${CAR.boardId}?replay=${CAR.runId}`,
      `/boards/${UI.boardId}?replay=${UI.runId}`,
    ])
    expect(screen.getAllByRole('link', { name: 'Look around' }).map((l) => l.getAttribute('href'))).toEqual([
      `/boards/${CAR.boardId}`,
      `/boards/${UI.boardId}`,
    ])
    expect(screen.getByRole('link', { name: 'All boards' }).getAttribute('href')).toBe('/boards')
  })

  it('leaves out boards this server lacks and says so when none are here', async () => {
    serve([])
    renderWith(<LandingPage />)
    expect(await screen.findByText('The demo boards are not on this server yet.')).toBeTruthy()
    expect(screen.queryAllByRole('link', { name: 'Show me how' })).toHaveLength(0)
  })

  it('embeds the video only when there is one', async () => {
    serve([CAR.boardId])
    const { container, unmount } = renderWith(<LandingPage />)
    await screen.findByText('Show me how')
    expect(container.querySelector('video')).toBeNull()
    unmount()
    SHOWCASE.videoUrl = '/demo.mp4'
    const second = renderWith(<LandingPage />)
    await screen.findByText('Show me how')
    expect(second.container.querySelector('video')?.getAttribute('src')).toBe('/demo.mp4')
  })
})

describe('App at /', () => {
  it('shows the landing page in demo mode', async () => {
    serve([CAR.boardId])
    renderWith(<App />)
    expect(await screen.findByRole('heading', { name: 'Muse' })).toBeTruthy()
  })

  it('shows the board list outside demo mode', async () => {
    serve([CAR.boardId], false)
    renderWith(<App />)
    expect(await screen.findByRole('heading', { name: 'Boards' })).toBeTruthy()
  })
})
