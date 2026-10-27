import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { useState } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useDialog } from './useDialog'

afterEach(cleanup)

function Dlg({ onClose }: { onClose: () => void }) {
  const dialog = useDialog<HTMLDivElement>(onClose)
  return (
    <div {...dialog} aria-label="Test dialog">
      <button type="button">First</button>
      <textarea aria-label="Note" />
      <button type="button" data-autofocus>
        Main
      </button>
      <button type="button">Last</button>
    </div>
  )
}

function Host({ onClose = () => {} }: { onClose?: () => void }) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        Opener
      </button>
      {open && (
        <Dlg
          onClose={() => {
            onClose()
            setOpen(false)
          }}
        />
      )}
    </>
  )
}

function openIt(onClose?: () => void) {
  render(<Host onClose={onClose} />)
  const opener = screen.getByRole('button', { name: 'Opener' })
  opener.focus()
  fireEvent.click(opener)
  return opener
}

describe('useDialog', () => {
  it('is modal and moves focus to the data-autofocus element on open', () => {
    openIt()
    const dlg = screen.getByRole('dialog', { name: 'Test dialog' })
    expect(dlg.getAttribute('aria-modal')).toBe('true')
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Main' }))
  })

  it('traps Tab and Shift+Tab inside', () => {
    openIt()
    const last = screen.getByRole('button', { name: 'Last' })
    const first = screen.getByRole('button', { name: 'First' })
    // fireEvent returns false when the handler called preventDefault (the browser would not move focus)
    last.focus()
    expect(fireEvent.keyDown(last, { key: 'Tab' })).toBe(false)
    expect(document.activeElement).toBe(first)
    expect(fireEvent.keyDown(first, { key: 'Tab', shiftKey: true })).toBe(false)
    expect(document.activeElement).toBe(last)
    // in the middle, the browser's own tab order is left alone
    const main = screen.getByRole('button', { name: 'Main' })
    main.focus()
    expect(fireEvent.keyDown(main, { key: 'Tab' })).toBe(true)
    expect(document.activeElement).toBe(main)
  })

  it('pulls focus back in when it lands outside the open dialog', () => {
    render(
      <>
        <button type="button">Outside</button>
        <Host />
      </>,
    )
    const opener = screen.getByRole('button', { name: 'Opener' })
    opener.focus()
    fireEvent.click(opener)
    screen.getByRole('button', { name: 'Outside' }).focus()
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'First' }))
  })

  it('Escape closes from inside an input and restores focus to the opener', () => {
    const onClose = vi.fn()
    const opener = openIt(onClose)
    const note = screen.getByRole('textbox', { name: 'Note' })
    note.focus()
    const windowKey = vi.fn()
    window.addEventListener('keydown', windowKey)
    fireEvent.keyDown(note, { key: 'Escape' })
    window.removeEventListener('keydown', windowKey)
    expect(onClose).toHaveBeenCalledTimes(1)
    expect(windowKey).not.toHaveBeenCalled() // the board's own Escape does not also fire
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(document.activeElement).toBe(opener)
  })

  describe('stacked dialogs', () => {
    function Stack({ onCloseTop, onCloseBottom }: { onCloseTop: () => void; onCloseBottom: () => void }) {
      const [top, setTop] = useState(false)
      const bottom = useDialog<HTMLDivElement>(onCloseBottom)
      return (
        <>
          <div {...bottom} aria-label="Bottom">
            <button type="button" onClick={() => setTop(true)}>
              B1
            </button>
            <button type="button">B2</button>
          </div>
          {top && (
            <Top
              onClose={() => {
                onCloseTop()
                setTop(false)
              }}
            />
          )}
        </>
      )
    }
    function Top({ onClose }: { onClose: () => void }) {
      const d = useDialog<HTMLDivElement>(onClose)
      return (
        <div {...d} aria-label="Top">
          <button type="button">T1</button>
          <button type="button">T2</button>
        </div>
      )
    }
    const open = (b = vi.fn(), t = vi.fn()) => {
      render(<Stack onCloseTop={t} onCloseBottom={b} />)
      fireEvent.click(screen.getByRole('button', { name: 'B1' }))
      return { b, t }
    }

    it('top dialog keeps focus and wraps Tab; the one below does not pull focus', () => {
      open()
      const t1 = screen.getByRole('button', { name: 'T1' })
      const t2 = screen.getByRole('button', { name: 'T2' })
      expect(screen.getByRole('dialog', { name: 'Top' })).toBeTruthy()
      t1.focus()
      expect(document.activeElement).toBe(t1)
      t2.focus()
      expect(fireEvent.keyDown(t2, { key: 'Tab' })).toBe(false)
      expect(document.activeElement).toBe(t1)
    })

    it('closing the top returns containment to the one below; Escape closes only the top', () => {
      const { b, t } = open()
      fireEvent.keyDown(screen.getByRole('button', { name: 'T1' }), { key: 'Escape' })
      expect(t).toHaveBeenCalledTimes(1)
      expect(b).not.toHaveBeenCalled()
      expect(screen.queryByRole('dialog', { name: 'Top' })).toBeNull()
      // containment is back on the bottom dialog
      const outside = document.body.appendChild(document.createElement('button'))
      outside.focus()
      expect(document.activeElement).toBe(screen.getByRole('button', { name: 'B1' }))
      outside.remove()
    })
  })
})
