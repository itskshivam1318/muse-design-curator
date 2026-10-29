import { cleanup, render } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { makeItem } from '../test/fixtures'
import { insideOverlay, isTyping, itemShortcut, toolShortcutAllowed } from './shortcutGuard'

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

describe('itemShortcut (v, i, x act on images, never on notes)', () => {
  const img = makeItem({ id: 'img' })
  const note = makeItem({ id: 'n1', kind: 'note', origin: 'note', note_text: 'Strap' })
  const flags = { explore: true, locked: false }

  it('does nothing with only a note selected', () => {
    for (const key of ['v', 'i', 'x']) expect(itemShortcut(key, [note], flags)).toBeNull()
  })

  it('acts on the image only when a note and an image are selected', () => {
    expect(itemShortcut('v', [note, img], flags)).toEqual({ kind: 'panel', panel: 'explore', itemId: 'img' })
    expect(itemShortcut('v', [img, note], { ...flags, explore: false })).toEqual({ kind: 'panel', panel: 'vary', itemId: 'img' })
    expect(itemShortcut('i', [note, img], flags)).toEqual({ kind: 'panel', panel: 'inspect', itemId: 'img' })
    expect(itemShortcut('x', [note, img], flags)).toEqual({ kind: 'notThis', items: [img] })
  })

  it('keeps the old rules: one item for v and i, x not on a locked demo, other keys are not item shortcuts', () => {
    const img2 = makeItem({ id: 'img2' })
    expect(itemShortcut('v', [img, img2], flags)).toBeNull()
    expect(itemShortcut('x', [img], { ...flags, locked: true })).toBeNull()
    expect(itemShortcut('f', [img], flags)).toBeNull()
  })
})
