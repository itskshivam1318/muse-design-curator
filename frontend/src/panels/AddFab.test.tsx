import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { LOCKED_TITLE } from '../demo'
import { AddFab } from './AddFab'

afterEach(cleanup)

const fab = () => screen.getByRole('button', { name: 'Add to board' })

describe('AddFab', () => {
  it('opens a popover with the add actions', () => {
    render(<AddFab onFiles={() => {}} onLink={async () => {}} />)
    expect(screen.queryByRole('group', { name: 'Add to board' })).toBeNull()
    fireEvent.click(fab())
    expect(fab().getAttribute('aria-expanded')).toBe('true')
    expect(screen.getByRole('group', { name: 'Add to board' })).toBeTruthy()
  })

  it('opening it moves focus to its first action', () => {
    render(<AddFab onFiles={() => {}} onLink={async () => {}} />)
    fireEvent.click(fab())
    const first = screen.getByRole('dialog', { name: 'Add to board' }).querySelector('button')!
    expect(document.activeElement).toBe(first)
  })

  it('Escape and outside click close it', () => {
    render(<AddFab onFiles={() => {}} onLink={async () => {}} />)
    fireEvent.click(fab())
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(screen.queryByRole('group', { name: 'Add to board' })).toBeNull()
    fireEvent.click(fab())
    fireEvent.mouseDown(document.body)
    expect(screen.queryByRole('group', { name: 'Add to board' })).toBeNull()
  })

  it('locked: the button is disabled with LOCKED_TITLE', () => {
    render(<AddFab onFiles={() => {}} onLink={async () => {}} disabled />)
    expect((fab() as HTMLButtonElement).disabled).toBe(true)
    expect(fab().getAttribute('title')).toBe(LOCKED_TITLE)
  })

  it('a chosen file calls onFiles and closes the popover', () => {
    const onFiles = vi.fn()
    render(<AddFab onFiles={onFiles} onLink={async () => {}} />)
    fireEvent.click(fab())
    const file = new File(['x'], 'a.png', { type: 'image/png' })
    fireEvent.change(screen.getByLabelText('Choose images or video to upload'), { target: { files: [file] } })
    expect(onFiles).toHaveBeenCalledWith([file])
    expect(screen.queryByRole('group', { name: 'Add to board' })).toBeNull()
  })
})
