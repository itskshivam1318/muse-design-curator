import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { Onboarding } from './Onboarding'

afterEach(cleanup)

describe('Onboarding', () => {
  it('shows three steps on an empty board', () => {
    const focus = vi.fn()
    const add = vi.fn()
    render(<Onboarding itemCount={0} onFocusContext={focus} onOpenAdd={add} />)
    expect(screen.getByText("Name this board and say what it's for")).toBeTruthy()
    expect(screen.getByText('Add references')).toBeTruthy()
    expect(screen.getByText('Add 5 to unlock board intelligence')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: /name this board/i }))
    expect(focus).toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: /add references/i }))
    expect(add).toHaveBeenCalled()
  })

  it('onboarding hidden once 1 item exists', () => {
    const { container } = render(
      <Onboarding itemCount={1} onFocusContext={() => {}} onOpenAdd={() => {}} />,
    )
    expect(container.innerHTML).toBe('')
    expect(screen.queryByText('Add references')).toBeNull()
  })
})
