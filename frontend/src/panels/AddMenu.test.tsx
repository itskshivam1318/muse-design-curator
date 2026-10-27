import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AddMenu } from './AddMenu'

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe('AddMenu', () => {
  it('shows the extension pairing code with the exact copy', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ code: '123456', expires_at: '' }), { status: 200 }),
    )
    render(<AddMenu open onOpenChange={() => {}} onFiles={() => {}} onLink={async () => {}} />)
    fireEvent.click(screen.getByRole('button', { name: /get the chrome extension/i }))
    await waitFor(() =>
      expect(screen.getByRole('dialog').textContent).toContain(
        'Install the extension, then enter this code: 123 456 (valid 10 minutes)',
      ),
    )
    expect(fetch).toHaveBeenCalledWith('/api/extension/pair-code', expect.objectContaining({ method: 'POST' }))
  })

  it('paste a link submits the URL', async () => {
    const onLink = vi.fn().mockResolvedValue(undefined)
    const onOpenChange = vi.fn()
    render(<AddMenu open onOpenChange={onOpenChange} onFiles={() => {}} onLink={onLink} />)
    fireEvent.click(screen.getByRole('button', { name: /paste a link/i }))
    fireEvent.change(screen.getByLabelText('Link to a page or image'), { target: { value: 'https://e.test/p' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add link' }))
    await waitFor(() => expect(onLink).toHaveBeenCalledWith('https://e.test/p'))
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false))
  })
})
