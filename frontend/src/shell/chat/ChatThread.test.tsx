import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { makeMessage, makeStep } from '../../test/fixtures'
import { ChatThread } from './ChatThread'
import type { Entry } from './thread'

afterEach(cleanup)

describe('ChatThread', () => {
  it('shows person and agent bubbles and steps as a short line', () => {
    const entries: Entry[] = [
      { kind: 'message', message: makeMessage({ id: 'm1', role: 'person', text: 'Find a warm palette' }) },
      { kind: 'step', step: makeStep({ say: 'Looking at the board' }) },
      { kind: 'message', message: makeMessage({ id: 'm2', role: 'agent', text: 'Here it is' }) },
    ]
    render(<ChatThread entries={entries} onFocusItem={() => undefined} />)
    expect(screen.getByText('Find a warm palette').closest('[data-role]')?.getAttribute('data-role')).toBe('person')
    expect(screen.getByText('Here it is').closest('[data-role]')?.getAttribute('data-role')).toBe('agent')
    expect(screen.getByText('Looking at the board')).toBeTruthy()
  })

  it('agent text item ids are clickable', () => {
    const onFocusItem = vi.fn()
    const entries: Entry[] = [{ kind: 'message', message: makeMessage({ text: 'I moved itm_1 to the left.' }) }]
    render(<ChatThread entries={entries} onFocusItem={onFocusItem} />)
    fireEvent.click(screen.getByRole('button', { name: 'itm_1' }))
    expect(onFocusItem).toHaveBeenCalledWith('itm_1')
  })

  it('a step about an item focuses it', () => {
    const onFocusItem = vi.fn()
    render(
      <ChatThread entries={[{ kind: 'step', step: makeStep({ say: 'Moved it', item_ids: ['itm_9'] }) }]} onFocusItem={onFocusItem} />,
    )
    fireEvent.click(screen.getByRole('button', { name: /Moved it/ }))
    expect(onFocusItem).toHaveBeenCalledWith('itm_9')
  })

  it('a question shows as text, or through renderQuestion', () => {
    const q = makeMessage({ id: 'q1', role: 'question', text: 'Which one?' })
    const { rerender } = render(<ChatThread entries={[{ kind: 'message', message: q }]} onFocusItem={() => undefined} />)
    expect(screen.getByText('Which one?')).toBeTruthy()
    rerender(
      <ChatThread
        entries={[{ kind: 'message', message: q }]}
        onFocusItem={() => undefined}
        renderQuestion={(m) => <p>asked: {m.text}</p>}
      />,
    )
    expect(screen.getByText('asked: Which one?')).toBeTruthy()
  })
})
