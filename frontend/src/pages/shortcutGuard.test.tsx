import { cleanup, render } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { insideOverlay, isTyping, toolShortcutAllowed } from './shortcutGuard'

afterEach(cleanup)

describe('insideOverlay', () => {
  it('is true inside a dialog or the right drawer, false on the board', () => {
    const { getByText } = render(
      <>
        <button type="button">board</button>
        <div role="dialog">
          <button type="button">in dialog</button>
        </div>
        <aside className="right-drawer">
          <button type="button">in drawer</button>
        </aside>
      </>,
    )
    expect(insideOverlay(getByText('in dialog'))).toBe(true)
    expect(insideOverlay(getByText('in drawer'))).toBe(true)
    expect(insideOverlay(getByText('board'))).toBe(false)
    expect(insideOverlay(null)).toBe(false)
    expect(insideOverlay(window)).toBe(false)
  })
})

describe('toolShortcutAllowed', () => {
  const key = (target: EventTarget, init: KeyboardEventInit) => {
    const e = new KeyboardEvent('keydown', init)
    Object.defineProperty(e, 'target', { value: target })
    return e
  }

  it('blocks typing targets, modifiers, and overlays (except Escape)', () => {
    const { getByText, getByLabelText } = render(
      <>
        <button type="button">board</button>
        <textarea aria-label="note" />
        <div role="dialog">
          <button type="button">in dialog</button>
        </div>
      </>,
    )
    expect(toolShortcutAllowed(key(getByText('board'), { key: 'n' }))).toBe(true)
    expect(toolShortcutAllowed(key(getByLabelText('note'), { key: 'n' }))).toBe(false)
    expect(toolShortcutAllowed(key(getByText('board'), { key: 'n', metaKey: true }))).toBe(false)
    expect(toolShortcutAllowed(key(getByText('in dialog'), { key: 'n' }))).toBe(false)
    expect(toolShortcutAllowed(key(getByText('in dialog'), { key: 'Escape' }))).toBe(true)
    expect(isTyping(getByLabelText('note'))).toBe(true)
  })
})
