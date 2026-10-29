import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { selection } from '../canvas/selection'
import { boardActivity } from '../events'
import { AgentCard } from './AgentCard'

afterEach(() => {
  cleanup()
  boardActivity.clear()
  selection.reset()
})

describe('AgentCard', () => {
  it('says nothing yet on a quiet board', () => {
    render(<AgentCard boardId="b1" />)
    expect(screen.getByText('Muse')).toBeTruthy()
    expect(screen.getByText('Nothing yet.')).toBeTruthy()
  })

  it('shows the latest activity as one sentence', () => {
    boardActivity.push('Added 2 images.')
    boardActivity.push('Palette finished on 3 images.')
    render(<AgentCard boardId="b1" />)
    expect(screen.getByText('Palette finished on 3 images.')).toBeTruthy()
    expect(screen.queryByText('Added 2 images.')).toBeNull()
    act(() => boardActivity.push('Kept Honey.'))
    expect(screen.getByText('Kept Honey.')).toBeTruthy()
  })

  it('has a visible but disabled input with a hidden label', () => {
    render(<AgentCard boardId="b1" />)
    const input = screen.getByLabelText('Message Muse') as HTMLInputElement
    expect(input.disabled).toBe(true)
    expect(input.placeholder).toBe('Agent coming soon')
    expect(screen.getByText('Message Muse').className).toContain('sr-only')
  })

  it('expand lists every entry, newest first', () => {
    boardActivity.push('first')
    boardActivity.push('second')
    boardActivity.push('third')
    render(<AgentCard boardId="b1" />)
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
    render(<AgentCard boardId="b1" />)
    expect(screen.getByRole('complementary', { name: 'Muse agent' })).toBeTruthy()
    act(() => selection.openDrawer('inspect', 'i1'))
    expect(screen.queryByRole('complementary', { name: 'Muse agent' })).toBeNull()
  })
})
