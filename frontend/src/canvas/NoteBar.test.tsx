import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, type Item } from '../api'
import { makeItem } from '../test/fixtures'
import { NoteBar } from './NoteBar'

afterEach(cleanup)

const noop = () => {}
const box = { x: 0, y: 0, width: 220, height: 96 }
const note = (over: Partial<Item> = {}) =>
  makeItem({ id: 'n1', kind: 'note', origin: 'note', note_text: 'Waxed canvas', ...over })

function renderBar(over: Partial<Item>, onReanalyse: (id: string) => Promise<unknown>) {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <NoteBar
        boardId="b1"
        note={note(over)}
        screen={box}
        readOnly={false}
        onVisualize={noop}
        onEdit={noop}
        onDelete={noop}
        onReanalyse={onReanalyse}
      />
    </QueryClientProvider>,
  )
  fireEvent.click(screen.getByRole('button', { name: 'More actions' }))
  return screen.getByRole('menuitem', { name: 'Re-analyse' }) as HTMLButtonElement
}

describe('NoteBar Re-analyse', () => {
  it('calls the action with the note id', () => {
    const onReanalyse = vi.fn(() => Promise.resolve())
    fireEvent.click(renderBar({}, onReanalyse))
    expect(onReanalyse).toHaveBeenCalledWith('n1')
  })

  it('is disabled while the note is pending or processing', () => {
    for (const parse_status of ['pending', 'processing'] as const) {
      expect(renderBar({ parse_status }, vi.fn()).disabled).toBe(true)
      cleanup()
    }
  })

  it('shows the daily limit inline', async () => {
    const message = 'Daily limit reached for this board, try tomorrow.'
    const onReanalyse = vi.fn(() => Promise.reject(new ApiError(429, 'DAILY_LIMIT', message)))
    fireEvent.click(renderBar({}, onReanalyse))
    expect((await screen.findByRole('alert')).textContent).toBe(message)
  })
})
